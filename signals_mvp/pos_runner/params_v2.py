"""Parametros da POS-RUNNER-V2 (PEDIDO CONSOLIDADO FASE 2): "V2 = config nova, versionada e com hash
proprio... Diferenca da V1 SOMENTE em parametros (sem codigo novo de detector)." Por isso este modulo
nao define nenhuma classe nova: reaproveita `ParamsV1` (mesmos campos, mesma validacao, MESMO calculo
de hash via `short_hash`) carregando `pos_runner_v2.yaml` em vez de `pos_runner_v1.yaml`. O detector
(`detector_v1.py`), o simulador (`simulate_v1.py`) e a banca (`bankroll_v1.py`) sao os MESMOS da V1,
rodando sobre os MESMOS candles (`pr_bars`) -- so o valor dos parametros muda."""

from __future__ import annotations

from pathlib import Path

from .params_v1 import ParamsV1, load_params_v1

CONFIG_PATH = Path(__file__).with_name("pos_runner_v2.yaml")


def load_params_v2(path: Path = CONFIG_PATH) -> ParamsV1:
    return load_params_v1(path)
