"""Diagnostico com a REDE REAL (somente leitura): GeckoTerminal, GoPlus e Telegram (getMe).

`teste-rede` nao envia mensagem nenhuma. `teste-telegram` envia UMA mensagem de teste.
Use na primeira vez no PC do operador (ou quando algo parecer errado).
"""

from __future__ import annotations

import os
import time

from .config import ConfigError, Paths, load_config
from .geckoterminal import GtClient
from .http import ApiError
from .logging_setup import make_stdout_safe
from .models import ChainCtx, norm_addr
from .metrics import compute_metrics
from .narrative import load_meta
from .telegram import TelegramClient, TelegramError
from .triggers import check_novo
from .util import fmt_age, fmt_usd, load_env
from .worker import CLOCK_SKEW_WARN_S, clock_skew_message, make_goplus, make_gt, meta_path


def _line(label: str, status: str, detail: str = "") -> None:
    print(f"  {label:<34} {status:<7} {detail}")


def _telegram(paths: Paths) -> TelegramClient | None:
    load_env(paths.env)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return None
    return TelegramClient(token, chat)


def run_netcheck(paths: Paths) -> int:
    make_stdout_safe()
    print("== Teste de rede (APIs reais, somente leitura; nenhuma mensagem e enviada) ==")
    try:
        cfg = load_config(paths.config)
    except ConfigError as exc:
        print("config.yaml INVALIDO:\n" + str(exc))
        return 1
    problems = 0
    gt: GtClient = make_gt(cfg)
    goplus = make_goplus(cfg)

    try:
        ids = gt.network_ids()
        _line("GeckoTerminal /networks", "OK", f"{len(ids)} redes")
    except ApiError as exc:
        _line("GeckoTerminal /networks", "FALHOU", str(exc))
        ids = set()
        problems += 1

    skew = gt.http.clock_skew_s()
    if skew is None:
        _line("Relogio do PC", "PULADO", "sem resposta do servidor para comparar")
    elif abs(skew) <= CLOCK_SKEW_WARN_S:
        _line("Relogio do PC", "OK", f"diferenca de {skew:+.1f}s para a internet")
    else:
        _line("Relogio do PC", "FALHOU", clock_skew_message(skew) or "")
        problems += 1

    for name, chain in cfg.enabled_chains().items():
        print(f"- {chain['nome']} ({name})")
        if ids and chain["gt_rede"] not in ids:
            _line("  rede no GeckoTerminal", "FALHOU", f"'{chain['gt_rede']}' nao existe: o bot vai DESLIGAR esta chain")
            problems += 1
            continue
        reference = frozenset(norm_addr(chain["plataforma"], a) for a in chain["ativos_referencia"])
        ctx = ChainCtx(name, chain["plataforma"], chain["gt_rede"], reference, frozenset(cfg["filtros"]["dex_liquidez_nao_confiavel"]))
        started = time.monotonic()
        try:
            pools = gt.new_pools(ctx, 1)
        except ApiError as exc:
            _line("  new_pools", "FALHOU", str(exc))
            problems += 1
            continue
        took = time.monotonic() - started
        if not pools:
            _line("  new_pools", "AVISO", "resposta vazia")
            continue
        fired = [p for p in pools if check_novo(p, cfg["filtros"], cfg["gatilhos"]["novo"], chain["liquidez_min_usd"]).fired]
        newest, oldest = min(p.age_s() or 0 for p in pools), max(p.age_s() or 0 for p in pools)
        _line("  new_pools", "OK", f"{len(pools)} pools em {took:.1f}s | idades {fmt_age(newest)}..{fmt_age(oldest)} | passariam no gatilho `novo` agora: {len(fired)}")
        sample = pools[0]
        metrics = compute_metrics(sample, cfg["plano"]["posicao_usd"])
        _line("  amostra", "OK", f"${sample.symbol} {sample.dex} MC {fmt_usd(metrics.mc)} liq {fmt_usd(metrics.liq)} vol_m5 {fmt_usd(metrics.vol_m5)} C/V {metrics.buys}/{metrics.sells}")
        tokens = [p.token for p in pools if p.token][:6]
        results, error = goplus.security(chain["plataforma"], chain["goplus_id"], tokens)
        if error is not None and not results:
            _line("  GoPlus", "FALHOU", str(error))
            problems += 1
        else:
            with_data = sum(1 for rec in results.values() if rec)
            _line("  GoPlus", "OK", f"{with_data}/{len(tokens)} tokens novos ja tem dado (o resto vira 'sem dado' — normal em token novo)")

    tg = _telegram(paths)
    if tg is None:
        _line("Telegram", "PULADO", "sem TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no .env")
    else:
        try:
            me = tg.get_me()
            _line("Telegram getMe", "OK", f"bot @{me.get('username', '?')} (chat id configurado: {tg.chat_id})")
        except TelegramError as exc:
            _line("Telegram getMe", "FALHOU", f"{exc} — confira o token no .env")
            problems += 1

    meta = load_meta(meta_path(paths, cfg))
    _line("meta.txt", "OK" if not meta.empty else "AVISO", f"{len(meta.groups)} grupo(s), versao_meta={meta.version}" + ("" if not meta.empty else " (vazio: sem pontos de narrativa)"))
    print("RESULTADO:", "OK" if problems == 0 else f"{problems} problema(s) — veja acima")
    return 0 if problems == 0 else 1


def run_telegram_test(paths: Paths) -> int:
    """Envia UMA mensagem de teste (confirma token + chat id)."""
    make_stdout_safe()
    tg = _telegram(paths)
    if tg is None:
        print("Preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no arquivo .env (copie do .env.example).")
        return 1
    try:
        tg.notify("✅ Teste do bot de sinais: se voce esta lendo isto, o token e o chat id estao certos. (PAPER / somente leitura)")
    except TelegramError as exc:
        print(f"FALHOU: {exc}\nConfira o token (@BotFather) e o chat id (@userinfobot). Abra o bot no Telegram e mande /start antes.")
        return 1
    print("Mensagem de teste enviada. Se chegou no seu Telegram, esta tudo certo.")
    return 0


def _fake_pos_runner_bars():
    """Mesmo padrao didatico dos testes do detector (graduacao -> runner -> queda -> zona -> rompimento), so pra
    gerar UMA entrada de mentira e confirmar que o alerta (com mini-grafico) chega no Telegram do operador."""
    from .pos_runner.candles import Bar

    def c(o: float, h: float, l: float, cl: float, v: float = 10.0):
        return (o, h, l, cl, v)

    rows = [c(60_000, 61_000, 59_000, 60_000)] * 2
    for p in (150_000, 300_000, 600_000, 900_000):
        rows.append(c(p * 0.9, p * 1.02, p * 0.88, p))
    rows.append(c(900_000, 1_000_000, 880_000, 950_000))                 # pico (1M)
    for p in (800_000, 600_000, 400_000, 250_000):
        rows.append(c(p * 1.1, p * 1.12, p * 0.97, p))
    rows.append(c(250_000, 255_000, 160_000, 165_000))                   # queda > 80%
    rows.append(c(165_000, 170_000, 150_000, 155_000))                   # fundo
    rows.append(c(155_000, 260_000, 154_000, 250_000))                   # 1o repique (R = 260k)
    rows += [c(240_000, 245_000, 200_000, 210_000)] * 4                  # lateral
    rows.append(c(210_000, 212_000, 175_000, 180_000))                   # teste de suporte (3 candles)
    rows.append(c(180_000, 182_000, 155_000, 162_000))
    rows.append(c(162_000, 200_000, 158_000, 195_000))
    rows += [c(220_000, 245_000, 205_000, 230_000)] * 8                  # lateral
    rows.append(c(240_000, 300_000, 238_000, 290_000))                   # rompimento de R
    rows.append(c(290_000, 292_000, 288_000, 290_000))                   # candle de entrada (open seguinte)
    start = 1_780_000_000
    step = 3600
    return [Bar(start + k * step, *r) for k, r in enumerate(rows)]


def run_pos_runner_telegram_test(paths: Paths) -> int:
    """Manda 1 alerta de ENTRADA de mentira (com mini-grafico, se o matplotlib estiver instalado) e 1 resumo de
    banca de mentira pro Telegram do operador -- confirma que a Parte B chega no celular antes de ligar pra valer
    (pedido do operador: ambos de mentira, nunca dado real)."""
    make_stdout_safe()
    tg = _telegram(paths)
    if tg is None:
        print("Preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no arquivo .env (copie do .env.example).")
        return 1
    from .pos_runner import charts
    from .pos_runner.detector import run as run_detector
    from .pos_runner.live import entry_text
    from .pos_runner.params import Params
    from .util import iso_utc, utc_now

    bars = _fake_pos_runner_bars()
    params = Params(age_window_days=(0.0, 10_000.0))   # so pra garantir "primario" nesta demonstracao
    det = run_detector(bars, params, "1h", l_bc=60_000.0, grad_ts=bars[0].ts, created_ts=bars[0].ts - 4 * 86400)
    entries = [e for e in det.events if e.kind == "ENTRADA"]
    if not entries:
        print("FALHOU: o padrao de demonstracao nao gerou uma entrada (bug no teste, nao no bot) -- avise quem mantem o codigo.")
        return 1
    ev = entries[0]
    data = dict(ev.data, n_entrada=1, close=bars[ev.idx].close)
    text = "[TESTE -- dado de mentira, nao e um sinal real]\n" + entry_text("TESTE", "pumpfun", "1h", "TokenDeMentira111111111111111111111111111", data,
                                                                              params.version, "pré-registrada")
    png = None
    if charts.available():
        lo = max(0, ev.data["peak_idx"] - 10)
        path = charts.plot_setup(paths.dados / "pos_runner" / "teste_telegram.png", bars, "1h",
                                 "TESTE POS-RUNNER [1h] — alerta de mentira", "pumpfun · so para confirmar a entrega",
                                 60_000.0, ev, [e for e in det.events if e.idx >= lo], (), (lo, ev.idx + 2))
        png = path.read_bytes() if path else None
    try:
        if png is not None:
            tg.send_photo(png, text)
        else:
            tg.notify(text + "\n(sem mini-gráfico: instale o matplotlib — signals_mvp\\instalar.bat)")
    except TelegramError as exc:
        print(f"FALHOU no alerta de entrada: {exc}")
        return 1

    resumo_txt = ("[TESTE -- dado de mentira, nao e um resumo real]\n"
                 "💰 Resumo diário da gestão de banca (US$100, posição 5%, até 3 abertas):\n"
                 f"- 1h/A: 3 trades | 67% com lucro | líquido médio +4.2% | banca US$ 106.30 | maior queda US$ 2.10 (2%)\n"
                 f"- 1h/B: 3 trades | 67% com lucro | líquido médio +3.8% | banca US$ 105.70 | maior queda US$ 2.40 (2%)\n"
                 f"({iso_utc(utc_now())[:10]}, dado de demonstração)")
    try:
        tg.notify(resumo_txt)
    except TelegramError as exc:
        print(f"FALHOU no resumo de banca: {exc}")
        return 1
    print("Alerta de entrada (com mini-gráfico, se disponível) e resumo de banca de teste enviados. Confira o Telegram.")
    return 0

