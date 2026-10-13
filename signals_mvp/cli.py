"""Linha de comando: python -m signals_mvp <comando>."""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .config import ConfigError, load_config, make_paths
from .logging_setup import make_stdout_safe

COMMANDS = """\
comandos:
  iniciar (ou sem argumento)  liga o bot (supervisor + worker, reinicia se cair)
  parar                       desliga o bot com seguranca (grava os CSVs)
  selfcheck                   testa tudo com dados falsos, sem rede
  teste-rede                  testa as APIs reais (GeckoTerminal, GoPlus, Telegram getMe), sem enviar mensagem
  teste-telegram              envia UMA mensagem de teste (confirma token e chat id do .env)
  config                      valida o config.yaml e mostra a versao (hash)
  resumo                      mostra o resumo de hoje (le o banco, sem rede)
  exportar                    regrava os CSVs a partir do banco
  worker                      (interno) roda so o worker, sem supervisor
"""


def _cmd_config(paths) -> int:
    try:
        cfg = load_config(paths.config)
    except ConfigError as exc:
        print("CONFIG INVALIDA:\n" + str(exc))
        return 2
    chains = ", ".join(f"{name}{'' if c['ligada'] else ' (desligada)'}" for name, c in cfg["chains"].items())
    print(f"config.yaml OK | versao_config = {cfg.version} | chains: {chains}")
    return 0


def _cmd_resumo(paths) -> int:
    from .storage import Storage
    from .summary import build_summary, local_day_bounds
    from .util import utc_now
    from datetime import datetime

    cfg = load_config(paths.config)
    storage = Storage(paths)
    now = utc_now()
    start, end = local_day_bounds(now)
    names = {k: v["nome"] for k, v in cfg["chains"].items()}
    print(build_summary(storage, start, min(end, now + 1), names, datetime.fromtimestamp(now).strftime("%d/%m/%Y")))
    storage.close()
    return 0


def _cmd_exportar(paths) -> int:
    from .storage import Storage

    storage = Storage(paths)
    written = storage.export_csvs(force=True)
    storage.close()
    print("CSVs regravados:", ", ".join(written) or "(nenhum: algum arquivo esta aberto no Excel?)", "|", paths.dados)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    make_stdout_safe()
    parser = argparse.ArgumentParser(prog="signals_mvp", description="Bot de sinais de memecoins (PAPER / somente leitura)", epilog=COMMANDS,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", nargs="?", default="iniciar",
                        choices=["iniciar", "run", "parar", "stop", "selfcheck", "teste-rede", "teste-telegram", "config", "resumo", "exportar", "worker"])
    parser.add_argument("--forcar", action="store_true", help="iniciar mesmo com um pid antigo no arquivo (so se tiver certeza)")
    args = parser.parse_args(argv)
    paths = make_paths()
    command = args.comando

    if command in ("iniciar", "run"):
        from .supervisor import run_supervisor

        return run_supervisor(paths, force=args.forcar)
    if command == "worker":
        from .worker import run_worker

        return run_worker(paths)
    if command in ("parar", "stop"):
        from .supervisor import request_stop

        return request_stop(paths)
    if command == "selfcheck":
        from .selfcheck import run_selfcheck

        return run_selfcheck()
    if command == "teste-rede":
        from .netcheck import run_netcheck

        return run_netcheck(paths)
    if command == "teste-telegram":
        from .netcheck import run_telegram_test

        return run_telegram_test(paths)
    if command == "config":
        return _cmd_config(paths)
    if command == "resumo":
        return _cmd_resumo(paths)
    if command == "exportar":
        return _cmd_exportar(paths)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
