"""Utilitarios pequenos e sem dependencia externa."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# tempo
# ---------------------------------------------------------------------------


def utc_now() -> float:
    """Relogio padrao do bot (epoch em segundos). Injetavel nos testes."""
    return time.time()


def iso_utc(ts: float | None) -> str:
    """Epoch -> 'YYYY-MM-DDTHH:MM:SSZ' (vazio se None). Todos os CSVs usam UTC."""
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Any) -> float | None:
    """'2026-10-13T13:37:23Z' -> epoch. Devolve None se nao der para ler."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# numeros
# ---------------------------------------------------------------------------


def to_float(value: Any) -> float | None:
    """Converte str/int/float em float finito; qualquer outra coisa vira None.

    A falta de dado fica explicita (None) e nunca vira zero.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return None if number is None else int(number)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def lerp01(value: float | None, zero_at: float, full_at: float) -> float:
    """Mapeia value linearmente para [0, 1] (zero_at -> 0, full_at -> 1).

    Funciona nos dois sentidos (zero_at > full_at significa 'menor e melhor').
    None vira 0.
    """
    if value is None or zero_at == full_at:
        return 0.0
    return clamp((value - zero_at) / (full_at - zero_at), 0.0, 1.0)


# ---------------------------------------------------------------------------
# hash de versao
# ---------------------------------------------------------------------------


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def short_hash(obj: Any, size: int = 12) -> str:
    """Hash curto e estavel de qualquer estrutura JSON (usado em versao_config/versao_meta)."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:size]


# ---------------------------------------------------------------------------
# formatacao (pt-BR) para o Telegram
# ---------------------------------------------------------------------------


def _comma(text: str) -> str:
    return text.replace(".", ",")


def fmt_usd(value: float | None) -> str:
    """85000 -> '85k'; 8500 -> '8,5k'; 1234567 -> '1,2M'; None -> 's/d'."""
    if value is None:
        return "s/d"
    absolute = abs(value)
    if absolute >= 1e9:
        text = f"{value / 1e9:.1f}B"
    elif absolute >= 1e6:
        text = f"{value / 1e6:.1f}M"
    elif absolute >= 1e4:
        text = f"{value / 1e3:.0f}k"
    elif absolute >= 1e3:
        text = f"{value / 1e3:.1f}k"
    else:
        text = f"{value:.0f}"
    return _comma(text)


def fmt_money(value: float) -> str:
    """1234.5 -> '1.234,50' (padrao brasileiro)."""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_mult(value: float | None) -> str:
    return "s/d" if value is None else _comma(f"{value:.1f}x")


def fmt_pct(value: float | None, digits: int = 0) -> str:
    return "s/d" if value is None else _comma(f"{value:.{digits}f}%")


def fmt_age(seconds: float | None) -> str:
    if seconds is None:
        return "s/d"
    seconds = max(0.0, seconds)
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    return f"{int(seconds // 3600)} h {int(seconds % 3600 // 60):02d}"


# ---------------------------------------------------------------------------
# segredos e texto nao confiavel
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
_BOT_URL_RE = re.compile(r"(/bot)[^/\s\"']+")


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove o token do Telegram (e qualquer segredo conhecido) de um texto de log."""
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***")
    text = _BOT_URL_RE.sub(r"\1***", text)
    return _TOKEN_RE.sub("***", text)


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean_text(value: Any, limit: int = 80) -> str:
    """Texto vindo da chain/API e nao confiavel: sem quebra de linha e com tamanho limitado."""
    if value is None:
        return ""
    return _CONTROL_RE.sub(" ", str(value)).strip()[:limit]


def csv_safe(value: Any) -> str:
    """Neutraliza 'injecao de formula' no Excel (nome de token pode comecar com = + - @)."""
    text = clean_text(value, limit=200)
    if text and text[0] in "=+-@":
        return "'" + text
    return text


# ---------------------------------------------------------------------------
# arquivos
# ---------------------------------------------------------------------------


def atomic_write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    """Grava o CSV inteiro num temporario e troca de uma vez (leitor nunca ve arquivo pela metade).

    UTF-8 com BOM para o Excel do Windows nao estragar tickers em chines/emoji.
    Pode levantar PermissionError se o arquivo estiver aberto no Excel; quem chama decide.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_env(path: Path) -> list[str]:
    """Le um .env simples (CHAVE=valor) para os.environ sem sobrescrever o que ja existe.

    Devolve so os NOMES carregados (nunca valores) para log.
    """
    loaded: list[str] = []
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ and value != "":
            os.environ[key] = value
            loaded.append(key)
    return loaded


def get_path(data: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    """get_path(cfg, 'a.b.c') sem estourar KeyError."""
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current
