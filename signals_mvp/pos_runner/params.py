"""Parametros do POS-RUNNER-V0 (config versionada: o hash vai em cada linha de log).

Os valores padrao abaixo sao as REGRAS DO OPERADOR (decisoes de 2026-10-16 sobre o relatorio do Passo 0), que
substituem a secao 2 do handoff onde ela conflita. O arquivo `pos_runner_v0.yaml` e a fonte; ele so vale depois do
pre-registro (hash congelado). Duracoes em NUMERO DE CANDLES do timeframe.

Medidas (escolha conservadora para o que o operador nao respondeu): pico, queda, suporte e resistencia pelos
EXTREMOS reais dos candles (maxima e minima — o preco negociou ali); decisoes de rompimento, recuperacao e
invalidacao pelo FECHAMENTO.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional

import yaml

from ..util import short_hash

TIMEFRAMES = ("5m", "1h", "4h")
CONFIG_PATH = Path(__file__).with_name("pos_runner_v0.yaml")


@dataclass(frozen=True)
class Params:
    # fase 1 — runner
    runner_min_mc: float = 300_000.0           # pico de MC (maxima) desde o inicio da onda >= isto
    peak_bands: tuple = (500_000.0, 1_000_000.0, 5_000_000.0)   # faixas de pico (ATRIBUTO): 300-500k, 500k-1M, 1-5M, >5M
    # fase 2 — queda e zona
    drop_min: float = 0.80                     # queda (minima desde o pico) >= 80% -> fase 2
    drop_max: float = 0.90                     # queda > 90% = moeda morta (onda invalida)
    support_min_lbc: float = 0.75              # fundo (suporte S) >= 0,75 x L_bc; abaixo = onda invalida
    support_attr_mc: float = 100_000.0         # "fase 2 normalmente acima de 100k": ATRIBUTO (S >= isto), nao filtro
    zone_min_candles: int = 12                 # zona madura: >= isto de candles desde o fundo
    # testes de suporte (episodios de 1 ou muitos candles)
    test_zone: float = 0.10                    # teste comeca quando a minima <= S x (1 + isto)
    recover_mult: float = 1.25                 # recupera quando fecha >= min((S + R) / 2, S x isto)
    tests_min: int = 1                         # zona madura: >= isto de testes completos (descida + recuperacao)
    test_break: float = 0.02                   # fechamento < minima do ultimo teste x (1 - isto) = setup morto
    stop_below_test: float = 0.03              # stop = minima do ultimo teste x (1 - isto)
    # fase 3 — entrada (fechamento acima de R, SEM exigencia de volume)
    atr_period: int = 20
    power_atr_mult: float = 3.0                # power candle = amplitude >= isto x ATR(20 candles anteriores)
    absurd_frac: float = 0.50                  # candle que cobre >= 50% de R ate P_peak = absurdo (veto)
    age_window_days: tuple = (2.0, 7.0)        # idade desde a CRIACAO do token na entrada (filtro primario, todos os tf)
    # saidas
    tp_frac_of_peak: float = 0.95              # alvo = 0,95 x P_peak
    exhaustion_peak_frac: float = 0.85         # exaustao = power candle com maxima >= 0,85 x P_peak -> sai no open seguinte
    time_stop_candles: int = 48
    partial_frac: float = 0.50                 # saida B: vende isto no alvo e move o stop do resto para a entrada
    trail_frac: float = 0.25                   # saida B: resto em trailing de 25% da maxima

    def __post_init__(self) -> None:
        if not 0 < self.drop_min < self.drop_max < 1:
            raise ValueError("precisa 0 < drop_min < drop_max < 1")
        if self.zone_min_candles < 2 or self.tests_min < 0:
            raise ValueError("zona: zone_min_candles >= 2 e tests_min >= 0")
        if not (0 < self.test_zone < 1 and self.recover_mult > 1 + self.test_zone):
            raise ValueError("teste: 0 < test_zone < 1 e recover_mult > 1 + test_zone (a recuperacao fica acima da regiao do suporte)")
        if self.atr_period < 2 or self.time_stop_candles < 1:
            raise ValueError("atr_period >= 2 e time_stop_candles >= 1")
        if len(self.age_window_days) != 2 or self.age_window_days[0] > self.age_window_days[1]:
            raise ValueError("age_window_days = [minimo, maximo]")
        if list(self.peak_bands) != sorted(self.peak_bands) or not self.peak_bands or self.peak_bands[0] <= self.runner_min_mc:
            raise ValueError("peak_bands: limites crescentes acima de runner_min_mc")

    def age_window(self, tf: str) -> Optional[tuple[float, float]]:  # noqa: ARG002 - a mesma janela em todos os tf
        return float(self.age_window_days[0]), float(self.age_window_days[1])

    def peak_band(self, peak: Optional[float]) -> str:
        """Faixa do pico do runner (atributo): 300-500k, 500k-1M, 1-5M, >5M."""
        if peak is None or peak < self.runner_min_mc:
            return "?"
        names = ("300-500k", "500k-1M", "1-5M")
        for limit, name in zip(self.peak_bands, names):
            if peak < limit:
                return name
        return ">5M"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["peak_bands"] = [float(x) for x in self.peak_bands]
        d["age_window_days"] = [float(x) for x in self.age_window_days]
        return d

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
        elif isinstance(default, tuple):
            clean[name] = tuple(float(x) for x in value)
        else:
            clean[name] = value
    return Params(**clean)


def is_preregistered(text: str, version: str) -> bool:
    """O pre-registro esta congelado com ESTA config: a linha de status (a 1a linha que comeca com "Status:") diz
    PRE-REGISTRADO e o hash aparece no documento. So a linha de status conta: o texto pode citar o status final."""
    status = re.search(r"^Status:(.*)$", text, re.M)
    return bool(status and re.match(r"\s*\*\*PRE-REGISTRADO", status.group(1))) and version in text


def load_params(path: Path = CONFIG_PATH) -> Params:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return params_from_dict(raw.get("parametros") or {})
