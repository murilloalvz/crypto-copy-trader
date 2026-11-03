"""Parametros da POS-RUNNER-V3 ("ideia pura: segunda corrida pos-queda", PEDIDO 2026-11-02, Passo 1).

MESMO detector/simulador da V1 (`detector_v1.py`/`simulate_v1.py`, ZERO codigo novo de deteccao) --
`ParamsV3` e uma subclasse de `ParamsV1` com os MESMOS campos (reaproveitados 1:1, nunca redefinidos)
e so 2 defaults proprios (`zone_min_candles=4`, `age_window_days=(0.0, 36_500.0)` -- ver
`pos_runner_v3.yaml` para a justificativa de cada um). Hash PROPRIO: `POS_RUNNER_TAG="V3"` (herdado
de `ParamsV1.POS_RUNNER_TAG="V1"`, sobrescrito aqui) entra no calculo de `version` -- mesmo que um
futuro `ParamsV3(**valores_da_v1)` tenha o MESMO `as_dict()` de uma `ParamsV1()`, o hash ainda
diverge (tag diferente), porque a V3 e um contrato de medicao realmente novo (covariaveis em
`pos_runner_v3.py`), nunca so um retune de parametro da V1/V2. V1 (`279b79ffa3f0`) e V2
(`d57b4331d51d`) ficam INTOCADOS por este modulo -- `params_v1.py` so ganhou um `ClassVar`/parametro
`cls` opcional, comportamento IDENTICO a antes pra quem nunca passa `cls` (ver teste de regressao em
`tests/test_params_v3.py`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .params_v1 import ParamsV1, load_params_v1, params_v1_from_dict

CONFIG_PATH = Path(__file__).with_name("pos_runner_v3.yaml")


@dataclass(frozen=True)
class ParamsV3(ParamsV1):
    POS_RUNNER_TAG: ClassVar[str] = "V3"
    zone_min_candles: int = 4
    age_window_days: tuple = (0.0, 36_500.0)


def params_v3_from_dict(raw: dict) -> ParamsV3:
    return params_v1_from_dict(raw, cls=ParamsV3)


def load_params_v3(path: Path = CONFIG_PATH) -> ParamsV3:
    return load_params_v1(path, cls=ParamsV3)
