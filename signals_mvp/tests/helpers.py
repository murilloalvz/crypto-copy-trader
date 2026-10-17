"""Montagem do engine de teste (tudo em pasta temporaria, sem rede, relogio falso)."""

from __future__ import annotations

import copy
import csv
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from ..config import PACKAGE_DIR, Config, build_config, load_config, make_paths
from ..engine import Engine
from ..narrative import parse_meta
from ..storage import Storage
from .fakes import FakeClock, FakeGoPlus, FakeGt, FakeTelegram

TEST_META = "IA: ai, agent, gpt\nGATO: cat, gato, kitty\nPOLITICA: trump\n"


def shipped_config() -> Config:
    return load_config(PACKAGE_DIR / "config.yaml")


def config_with(overrides: Optional[dict] = None) -> Config:
    """Config enviada com o pacote + alteracoes aninhadas (ex.: {'score': {'minimo_alerta': 50}})."""
    raw = copy.deepcopy(shipped_config().raw)

    def merge(target: dict, patch: dict) -> None:
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = value

    merge(raw, overrides or {})
    return build_config(raw)


class Env:
    """Tudo que um teste de engine precisa."""

    def __init__(self, overrides: Optional[dict] = None, telegram: bool = True):
        self.tmp = Path(tempfile.mkdtemp(prefix="signals_mvp_test_"))
        self.paths = make_paths(self.tmp)
        self.clock = FakeClock()
        self.storage = Storage(self.paths)
        self.gt = FakeGt(self.clock)
        self.goplus = FakeGoPlus()
        self.tg: Optional[FakeTelegram] = FakeTelegram() if telegram else None
        self.cfg = config_with(overrides)
        self.meta = parse_meta(TEST_META)
        self.engine = Engine(self.cfg, self.meta, self.storage, self.gt, self.goplus, self.tg, clock=self.clock, sleep=lambda s: None)

    def cycle(self, n: int = 1, step: float = 45.0):
        stats = None
        for _ in range(n):
            stats = self.engine.run_cycle()
            self.clock.advance(step)
        return stats

    def read(self, name: str) -> list[dict]:
        return read_csv(self.paths.dados / name)

    def close(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
