"""Parametros do POS-RUNNER-V0 (config versionada: o hash vai em cada linha de log).

Os valores padrao abaixo sao os do handoff (secao 2). O arquivo `pos_runner_v0.yaml` e a fonte; o Passo 0
(calibracao com os 5 exemplos) pode propor mudancas, que so valem depois do OK do operador e do
pre-registro (hash congelado). Todas as duracoes sao em NUMERO DE CANDLES do timeframe.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

import yaml

from ..util import short_hash

TIMEFRAMES = ("5m", "1h", "4h")
CONFIG_PATH = Path(__file__).with_name("pos_runner_v0.yaml")


@dataclass(frozen=True)
class Params:
    # fase 1 — runner
    runner_min_mc: float = 300_000.0          # pico de MC desde a graduacao (piso)
    # fase 2 — pullback
    drop_min: float = 0.80                     # queda minima a partir do pico (fase 2 comeca)
    drop_max: float = 0.90                     # queda maxima; passou disso -> onda invalida
    measure: str = "wick"                      # pico/queda/caixa por "wick" (max/min), "close" ou "body" (corpos)
    bounce_fractal: int = 2                    # 1o repique = 1o topo fractal (k candles de cada lado) depois da queda
    box_min_candles: int = 12                  # maturacao minima da caixa
    box_max_ratio: float = 3.0                 # caixa contida: R/S <= isto
    # wicks (martelos no suporte)
    wick_zone: float = 0.05                    # minima dentro de S +- 5%
    wick_body_mult: float = 2.0                # pavio inferior >= 2x o corpo
    wick_min: int = 1                          # minimo de wicks para armar o setup
    wick_break: float = 0.02                   # fechamento < minima da ultima wick x (1 - isto) -> invalida
    # fase 3 — entrada
    breakout_vol_mult: float = 2.0             # volume do candle de rompimento >= isto x media da caixa
    atr_period: int = 20
    power_atr_mult: float = 3.0                # power candle = amplitude >= isto x ATR(20)
    absurd_frac: float = 0.50                  # candle cobre >= 50% de R -> P_peak = absurdo (nao entra)
    age_window_days: dict = field(default_factory=lambda: {"5m": None, "1h": [2.0, 7.0], "4h": [2.0, 7.0]})
    # stop e saidas
    stop_below_wick: float = 0.03              # stop = minima da ultima wick x (1 - isto)
    tp_frac_of_peak: float = 0.95              # alvo = 0,95 x P_peak
    tp_reference: str = "measure"              # pico do alvo: "measure" (o da estrutura) ou "wick" (topo real, maxima)
    exhaustion_gain: float = 0.50              # power candle verde com preco >= +50% desde a entrada -> sai
    time_stop_candles: int = 48
    partial_frac: float = 0.50                 # saida B: vende isto no alvo
    trail_frac: float = 0.25                   # saida B: resto em trailing de 25% da maxima

    def __post_init__(self) -> None:
        if not 0 < self.drop_min < self.drop_max < 1:
            raise ValueError("precisa 0 < drop_min < drop_max < 1")
        if self.measure not in ("wick", "close", "body"):
            raise ValueError("measure deve ser 'wick', 'close' ou 'body'")
        if self.box_min_candles < 2 or self.box_max_ratio <= 1 or self.bounce_fractal < 1:
            raise ValueError("caixa: box_min_candles >= 2, box_max_ratio > 1, bounce_fractal >= 1")
        if self.tp_reference not in ("measure", "wick"):
            raise ValueError("tp_reference deve ser 'measure' ou 'wick'")
        if self.atr_period < 2 or self.time_stop_candles < 1:
            raise ValueError("atr_period >= 2 e time_stop_candles >= 1")

    def age_window(self, tf: str) -> Optional[tuple[float, float]]:
        window = self.age_window_days.get(tf)
        return None if window is None else (float(window[0]), float(window[1]))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def version(self) -> str:
        return short_hash({"pos_runner": "V0", "params": self.as_dict()})


def params_from_dict(raw: dict[str, Any]) -> Params:
    """Valida nomes e normaliza tipos (300000 e 300000.0 precisam dar o MESMO hash)."""
    defaults = Params()
    known = {f.name for f in fields(Params)}
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
        elif name == "age_window_days":
            clean[name] = {str(tf): (None if w is None else [float(w[0]), float(w[1])]) for tf, w in dict(value).items()}
        else:
            clean[name] = value
    return Params(**clean)


def load_params(path: Path = CONFIG_PATH) -> Params:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return params_from_dict(raw.get("parametros") or {})
