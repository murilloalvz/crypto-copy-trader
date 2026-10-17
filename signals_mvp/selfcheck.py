"""Self-check SEM REDE: roda os testes automaticos e uma simulacao com token falso.

Serve para o operador confirmar, logo depois de instalar, que o bot funciona no PC dele
(Python, dependencias, SQLite, CSV, formatacao do alerta). Nao toca em nenhuma API.
"""

from __future__ import annotations

import contextlib
import html
import io
import logging
import re
import sys
import time
import unittest
from pathlib import Path


def _run_unit_tests() -> tuple[int, int, float, str]:
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent / "tests"), pattern="test_*.py", top_level_dir=str(Path(__file__).resolve().parent.parent))
    stream = io.StringIO()
    started = time.monotonic()
    with contextlib.redirect_stdout(io.StringIO()):  # alguns testes imprimem (ex.: o comando `parar`)
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    problems = len(result.failures) + len(result.errors)
    detail = stream.getvalue() if problems else ""
    return result.testsRun, problems, time.monotonic() - started, detail


def _simulation() -> list[str]:
    """Roda ~75 min de mercado falso em 1 s e devolve linhas de relatorio (levanta AssertionError se algo estiver errado)."""
    from .tests.fakes import SOL_TOKEN, T0, SimPool
    from .tests.helpers import Env
    from .tests.test_engine_e2e import rising

    env = Env()
    out: list[str] = []
    try:
        env.gt.add(SimPool(
            chain="solana", pool="POOL1", token=SOL_TOKEN, symbol="KittyAI", created_ts=T0,
            vol_m5=lambda a: 0.0 if a < 60 else 12000.0, buys=lambda a: 0 if a < 60 else 60, sells=lambda a: 0 if a < 60 else 20,
            buyers=lambda a: 0 if a < 60 else 40, liq=lambda a: 40000.0, price=rising,
        ))
        env.cycle(100)
        assert len(env.tg.sent) >= 1, "nenhum alerta foi gerado na simulacao"
        text, keyboard = env.tg.sent[0]
        plain = html.unescape(re.sub(r"</?code>", "", text))
        out.append("Alerta que seria enviado ao Telegram (dados FALSOS):")
        out.append("  " + "-" * 44)
        out.extend("  " + line for line in plain.splitlines())
        buttons = " ".join(f"[{b['text']}]" for row in keyboard["inline_keyboard"] for b in row)
        out.append(f"  {buttons}")
        out.append("  " + "-" * 44)
        rows = env.read("sinais.csv")
        first = rows[0]
        assert first["tp1_antes_sl"] in ("sim", "nao", "ambiguo", "nenhum"), "acompanhamento nao fechou"
        out.append(
            f"sinais.csv: {len(rows)} linha(s) | etiqueta={first['etiqueta']} score={first['score']} enviado={first['enviado']} "
            f"tp1_antes_sl={first['tp1_antes_sl']} resultado_liq={first['resultado_liq']}% latencia_s={first['latencia_s']}"
        )
        out.append(f"versao_config={first['versao_config']} versao_meta={first['versao_meta']}")
    finally:
        env.close()
    return out


def run_selfcheck() -> int:
    print("== Self-check do bot de sinais (sem rede, dados falsos) ==")
    logging.disable(logging.CRITICAL)  # os testes provocam avisos de proposito; nao poluir o console do operador
    try:
        return _run_selfcheck()
    finally:
        logging.disable(logging.NOTSET)


def _run_selfcheck() -> int:
    from .config import ConfigError, load_config, make_paths

    paths = make_paths()
    ok = True
    try:
        cfg = load_config(paths.config)
        print(f"[1/3] config.yaml valido | versao_config={cfg.version} | chains ligadas: {', '.join(cfg.enabled_chains())}")
    except ConfigError as exc:
        print("[1/3] config.yaml INVALIDO:\n" + str(exc))
        return 1

    print("[2/3] Rodando os testes automaticos ... ", end="", flush=True)
    tests, problems, seconds, detail = _run_unit_tests()
    if problems:
        ok = False
        print(f"FALHOU ({problems} problema(s) em {tests} testes)")
        print(detail[-4000:])
    else:
        print(f"OK ({tests} testes em {seconds:.0f}s)")

    print("[3/3] Simulacao de ponta a ponta ...")
    try:
        for line in _simulation():
            print("      " + line)
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"      FALHOU: {type(exc).__name__}: {exc}")

    print("RESULTADO:", "OK - pode rodar o bot." if ok else "FALHOU - nao rode o bot antes de corrigir.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_selfcheck())
