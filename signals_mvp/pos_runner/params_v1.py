"""Parametros da estrategia POS-RUNNER-V1 ("regras do professor"): config PROPRIA, versionada (hash em
`versao_config_v1`), completamente separada dos parametros do V0 (`params.py`) — mudar um nunca muda o hash do
outro, e os dois tem suas proprias tabelas/CSVs. Ver `docs/pos-runner-v1/INTERPRETACOES.md` para a
justificativa de cada limiar que o prompt original deixou em aberto (gatilhos, exaustao, stop, VAMP_RISK,
dado_invalido, idade como filtro). Duracoes em NUMERO DE CANDLES do timeframe (igual ao V0).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from ..util import short_hash

TIMEFRAMES = ("5m", "1h", "4h")
CONFIG_PATH = Path(__file__).with_name("pos_runner_v1.yaml")


@dataclass(frozen=True)
class ParamsV1:
    # timeframe principal (item 2.5: padrao so 1h, 5m/4h desligados para poupar orcamento do GeckoTerminal)
    timeframes: tuple = ("1h",)
    # idade (item 2.2): filtro REAL (nao so atributo como no V0 -- ver INTERPRETACOES.md #10a)
    age_window_days: tuple = (2.0, 7.0)
    # janela de ouro (item 2.3): nunca filtra: so rotula/prioriza. BRT fixo UTC-3 (sem horario de verao)
    janela_ouro_brt: tuple = ("08:30", "14:00")
    # anti-lixo (item 2.4): MC atual (ultimo candle fechado) abaixo disso = filtrado_mc_baixo (contado, nunca alerta)
    min_mc_usd: float = 100_000.0
    # setup 1 -- range / bear trap (item 2.5): mesma mecanica de zona/teste do detector V0 (zone_min_candles,
    # wicks de rejeicao), limiares proprios da V1
    runner_min_mc: float = 300_000.0          # pico minimo (filtro)
    peak_attr_mc: float = 500_000.0           # pico "atributo" citado no prompt (nunca filtro adicional)
    drop_min: float = 0.80
    drop_max: float = 0.90
    zone_min_candles: int = 12
    wicks_min: int = 1
    wicks_max: int = 3
    test_zone: float = 0.05                   # zona do suporte para contar wick/reacao_suporte: S x (1 +- isto)
    recover_mult: float = 1.25                # mesma definicao de "recuperou" do V0 (Zone._recovered)
    # gatilhos (item 2.6 + INTERPRETACOES.md #1)
    atr_period: int = 20
    power_atr_mult: float = 3.0               # power_candle_rompimento E power candle de exaustao (item 2.9)
    vol_mult: float = 2.0                     # rompimento_volume: volume >= isto x media da caixa
    # saidas (item 2.9 + INTERPRETACOES.md #2)
    tp1_frac: float = 0.30                    # fracao vendida no TOPO (TP1)
    exhaustion_wick_mult: float = 2.0         # pavio superior >= isto x o corpo = exaustao
    exhaustion_doji_frac: float = 0.60        # corpo ~0 (doji): pavio superior >= isto x amplitude = exaustao
    # stop (item 2.8 + INTERPRETACOES.md #3)
    stop_below_wick_pct: float = 0.02         # stop = minima do menor wick x (1 - isto)
    risk_min: float = 0.15                    # faixa de risco esperado (ATRIBUTO: fora dela so marca a tag)
    risk_max: float = 0.22
    # dado_invalido ao vivo (item 3.6 + INTERPRETACOES.md #6) -- parte do hash da V1 desde o 1o congelamento
    # (diferente do V0, que so emendou isto DEPOIS de congelado: aqui a V1 nasce ja com a regra)
    candle_wick_ratio_max: float = 3.0
    l_bc_floor_usd: float = 100.0
    # teto de SANIDADE (revisao da FASE 1, 2026-10-22): agnostico de launchpad, NAO e uma precisao por
    # launchpad -- este repo nao tem parametro de graduacao sourced para Raydium LaunchLab nem Meteora DBC
    # (DBC e documentado como configuravel por projeto; LaunchLab nunca foi pesquisado). US$10M e generoso
    # o bastante para nunca penalizar uma graduacao legitima de bonding curve (pump.fun mede 28-70k; mesmo
    # uma DBC/LaunchLab fora da curva tipica do pump.fun nao raise bilhoes numa bonding curve) e pega o
    # defeito ja diagnosticado do GT em DBC (L_bc relatado de centenas de milhares a ~US$4bi).
    l_bc_ceiling_usd: float = 10_000_000.0
    # tamanho/banca (item 2.10)
    banca_inicial_usd: float = 100.0
    mao_fixa_usd: float = 10.0                # banca < banca_fixa_limite_usd: mao fixa
    banca_fixa_limite_usd: float = 200.0
    posicao_frac: float = 0.10                # banca >= banca_fixa_limite_usd: fracao da banca
    max_posicoes_abertas: int = 3
    stop_diario_frac: float = 0.10
    stop_diario_perdas_seguidas: int = 3
    stop_semanal_frac: float = 0.20

    def __post_init__(self) -> None:
        if not set(self.timeframes) <= set(TIMEFRAMES) or not self.timeframes:
            raise ValueError(f"timeframes precisa ser um subconjunto nao vazio de {TIMEFRAMES}")
        if len(self.age_window_days) != 2 or self.age_window_days[0] > self.age_window_days[1]:
            raise ValueError("age_window_days = [minimo, maximo]")
        if len(self.janela_ouro_brt) != 2:
            raise ValueError("janela_ouro_brt = [inicio, fim] em 'HH:MM'")
        if not 0 < self.drop_min < self.drop_max < 1:
            raise ValueError("precisa 0 < drop_min < drop_max < 1")
        if self.zone_min_candles < 2:
            raise ValueError("zone_min_candles >= 2")
        if self.wicks_min < 1 or self.wicks_min > self.wicks_max:
            raise ValueError("1 <= wicks_min <= wicks_max")
        if not (0 < self.test_zone < 1 and self.recover_mult > 1 + self.test_zone):
            raise ValueError("0 < test_zone < 1 e recover_mult > 1 + test_zone")
        if self.atr_period < 2:
            raise ValueError("atr_period >= 2")
        if not 0 < self.tp1_frac < 1:
            raise ValueError("0 < tp1_frac < 1")
        if not 0 < self.stop_below_wick_pct < 1:
            raise ValueError("0 < stop_below_wick_pct < 1")
        if not 0 <= self.risk_min <= self.risk_max:
            raise ValueError("0 <= risk_min <= risk_max")
        if self.peak_attr_mc <= self.runner_min_mc:
            raise ValueError("peak_attr_mc precisa ser > runner_min_mc")
        if self.candle_wick_ratio_max <= 1:
            raise ValueError("candle_wick_ratio_max > 1")
        if self.l_bc_floor_usd < 0:
            raise ValueError("l_bc_floor_usd >= 0")
        if self.l_bc_ceiling_usd <= self.l_bc_floor_usd:
            raise ValueError("l_bc_ceiling_usd > l_bc_floor_usd")
        if self.mao_fixa_usd <= 0 or self.banca_fixa_limite_usd <= 0 or not 0 < self.posicao_frac < 1:
            raise ValueError("mao_fixa_usd, banca_fixa_limite_usd > 0 e 0 < posicao_frac < 1")
        if self.max_posicoes_abertas < 1:
            raise ValueError("max_posicoes_abertas >= 1")

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timeframes"] = list(self.timeframes)
        d["age_window_days"] = [float(x) for x in self.age_window_days]
        d["janela_ouro_brt"] = list(self.janela_ouro_brt)
        return d

    @property
    def version(self) -> str:
        return short_hash({"pos_runner": "V1", "params": self.as_dict()})


def params_v1_from_dict(raw: dict[str, Any]) -> ParamsV1:
    """Valida nomes e normaliza tipos (300000 e 300000.0 precisam dar o MESMO hash)."""
    defaults = ParamsV1()
    known = {f.name for f in fields(ParamsV1)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"parametros desconhecidos: {sorted(unknown)}")
    clean: dict[str, Any] = {}
    for name, value in raw.items():
        default = getattr(defaults, name)
        if isinstance(default, bool) or isinstance(default, str):
            clean[name] = type(default)(value)
        elif isinstance(default, float):
            clean[name] = float(value)
        elif isinstance(default, int):
            if float(value) != int(value):
                raise ValueError(f"{name} precisa ser inteiro")
            clean[name] = int(value)
        elif isinstance(default, tuple):
            clean[name] = tuple(value)
        else:
            clean[name] = value
    return ParamsV1(**clean)


def load_params_v1(path: Path = CONFIG_PATH) -> ParamsV1:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return params_v1_from_dict(raw.get("parametros") or {})
