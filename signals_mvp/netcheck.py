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

