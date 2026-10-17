"""Logs: arquivo completo (rotativo, UTC) + console curto. O token do Telegram nunca vaza."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import time
from typing import Iterable

from .config import Paths
from .util import redact


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, datefmt: str | None, secrets: Iterable[str], utc: bool = False):
        super().__init__(fmt, datefmt)
        self._secrets = tuple(s for s in secrets if s)
        if utc:
            self.converter = time.gmtime  # type: ignore[assignment]

    def format(self, record: logging.LogRecord) -> str:  # inclui traceback ja formatado
        return redact(super().format(record), self._secrets)


class _ConsoleFilter(logging.Filter):
    """Console curto: so a linha de status/alertas (logger `console`) e avisos/erros."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == "signals_mvp.console" or record.levelno >= logging.WARNING


def make_stdout_safe() -> None:
    """Console do Windows (cp1252) quebra com emoji/chines no print: troca por '?' em vez de cair."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def setup_logging(paths: Paths, secrets: Iterable[str] = (), debug: bool = False, console: bool = True, filename: str = "signals_mvp.log") -> None:
    make_stdout_safe()
    root = logging.getLogger("signals_mvp")
    for old_handler in list(root.handlers):  # fecha (nao so descarta) os handlers de uma configuracao anterior
        root.removeHandler(old_handler)
        old_handler.close()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False
    secrets = tuple(secrets)

    paths.logs.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        paths.logs / filename, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(RedactingFormatter("%(asctime)sZ %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S", secrets, utc=True))
    root.addHandler(file_handler)

    if console:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.addFilter(_ConsoleFilter())
        stream_handler.setFormatter(RedactingFormatter("%(asctime)s %(message)s", "%H:%M:%S", secrets))
        root.addHandler(stream_handler)
    # a lib requests/urllib3 loga URLs (o do Telegram carrega o token): silencia
    # (sao roteadas pelos MESMOS handlers com redacao, em vez de cair no stderr cru)
    for noisy in ("urllib3", "requests"):
        lib = logging.getLogger(noisy)
        lib.handlers = list(root.handlers)
        lib.propagate = False
        lib.setLevel(logging.WARNING)
