"""Plano da Parte A: periodos de graduacao e sorteio das janelas de calendario (seed fixa), com hash.

Datas (a partir do dia do congelamento D):
- a API publica do GeckoTerminal so serve 180 dias; o plano comeca `margin_days` depois de D-180 para o comeco do
  periodo continuar disponivel durante o download;
- um token pertence ao periodo da sua GRADUACAO; ele e observado `horizon_days` depois da graduacao e um trade pode
  durar ate 48 candles de 4h (8 dias) — por isso a ultima graduacao usavel e D - (horizon + exit_days + folga);
- holdout = o ultimo terco do trecho usavel; embargo de 7 dias antes dele; discovery = o resto.
As janelas (`window_minutes`) de cada periodo sao embaralhadas com a seed; a ordem e processada ate a regra de
parada por contagem. Plano + hash ficam num JSON que precisa ser commitado junto do pre-registro.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...util import short_hash

DAY = 86400


def _date_ts(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class PeriodPlan:
    freeze_date: str                  # D, "AAAA-MM-DD" (dia do congelamento do pre-registro)
    free_days: int = 180              # historico da API publica do GeckoTerminal
    margin_days: int = 3              # folga no comeco (o historico anda 1 dia por dia)
    horizon_days: int = 14            # observacao por token depois da graduacao (pergunta 7 ao operador)
    exit_days: int = 9                # saida mais longa: 48 candles de 4h = 8 dias (+1 de folga)
    tail_margin_days: int = 1
    holdout_fraction: float = 1 / 3
    embargo_days: int = 7
    window_minutes: int = 30
    seed: int = 20261015
    launchpads: tuple[str, ...] = ("pumpfun", "raydium_launchlab", "meteora_dbc")

    def periods(self) -> dict[str, tuple[int, int]]:
        d = _date_ts(self.freeze_date)
        start = d - (self.free_days - self.margin_days) * DAY
        usable_end = d - (self.horizon_days + self.exit_days + self.tail_margin_days) * DAY
        if usable_end <= start:
            raise ValueError("periodo usavel vazio")
        span = usable_end - start
        hold_start = usable_end - int(span * self.holdout_fraction)
        hold_start -= hold_start % (self.window_minutes * 60)
        emb_start = hold_start - self.embargo_days * DAY
        return {"discovery": (start, emb_start), "embargo": (emb_start, hold_start), "holdout": (hold_start, usable_end)}

    def windows(self, period: str) -> list[tuple[int, int]]:
        """Janelas do periodo na ORDEM DO SORTEIO (deterministica pela seed)."""
        lo, hi = self.periods()[period]
        w = self.window_minutes * 60
        first = lo - lo % w + (w if lo % w else 0)
        slots = [(t, t + w) for t in range(first, hi - w + 1, w)]
        rng = random.Random(f"{self.seed}:{period}")
        rng.shuffle(slots)
        return slots

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["launchpads"] = list(self.launchpads)
        return d

    @property
    def version(self) -> str:
        return short_hash({"plano_parte_a": self.as_dict()})


def write_plan(plan: PeriodPlan, path: Path, params_version: str) -> dict[str, Any]:
    periods = plan.periods()
    doc = {
        "hipotese": "POS-RUNNER-V0",
        "versao_config": params_version,
        "versao_plano": plan.version,
        "plano": plan.as_dict(),
        "periodos": {k: {"inicio": _iso(a), "fim": _iso(b), "dias": round((b - a) / DAY, 1)} for k, (a, b) in periods.items()},
        "janelas": {k: len(plan.windows(k)) for k in ("discovery", "holdout")},
        "hash_ordem_discovery": short_hash(plan.windows("discovery"), 16),
        "hash_ordem_holdout": short_hash(plan.windows("holdout"), 16),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return doc


def load_plan(path: Path) -> PeriodPlan:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = dict(doc["plano"])
    raw["launchpads"] = tuple(raw["launchpads"])
    plan = PeriodPlan(**raw)
    if plan.version != doc["versao_plano"]:
        raise ValueError("plano alterado depois de gravado (hash nao bate)")
    return plan
