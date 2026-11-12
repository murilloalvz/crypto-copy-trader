"""PEDIDO 2026-11-12 (autorizado, rodada 18, item 3): implementacao do algoritmo EXATO pre-registrado
em `docs/pos-runner-v3/PREREGISTRO_ENTRADA_SUPORTE_2026-11-12.md` (texto CONGELADO por hash --
`garantir_entrada_suporte_registrada`, MESMO padrao de `saida_fiel.garantir_saida_fiel_registrada`;
nunca editado depois de registrado). PAPER/READ-ONLY. `DetectorV1`/`ParamsV3`/criterio de sinal da V3
intocados -- este modulo so RECONSTITUI causalmente a sequencia de eventos JA decidida pelo detector
oficial (zero mudanca de regra, zero chamada de rede, zero escrita em `pr3_signals`/alertas).

So a mecanica de "reconstruir a caixa e achar revisitas ao suporte" mora aqui (depende so de
`detector_v1`/`candles`, nunca de `scripts/`, pra nao inverter a camada scripts->pos_runner). A
montagem do sinal sintetico (`_montar_sinal`), a saida A oficial (`horizonte_fixo.
calcular_r_horizonte`) e os comparadores (a)/(b)/(c) do pedido moram em
`scripts/avaliar_entrada_suporte.py`, que importa este modulo E `scripts/varredura_v3.py`.

Resumo do algoritmo (ver o pre-registro pra texto completo/motivacao -- esta hipotese foi motivada
por achados exploratorios ja vistos, rodada 11 item B4, nunca um pre-registro "a frio"):
1. Reexecuta `DetectorV1` (MESMOS `ParamsV3`/bars/l_bc/created_ts do sinal real, `grad_ts=None` --
   so afeta `idade_grad_dias`, nunca a mecanica de zona/gatilho) candle a candle, 0..gatilho_idx-1.
2. "Caixa formada" = indice do evento WATCHLIST da MESMA zona do sinal real.
3. "Revisita ao suporte S (= fundo da caixa, MESMO valor neste detector)": candle, apos a caixa
   formada e antes do gatilho real, cujo low toca a banda `S x (1 +- test_zone)` -- S tomado no
   MOMENTO (replay incremental, nunca o valor final). Candles consecutivos dentro da banda contam
   como UMA revisita so (decidida no 1o candle que entra na banda).
4. Stop = S(no momento da revisita) x (1 - stop_below_wick_pct) -- MESMA formula oficial do stop."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Optional

from ..util import short_hash
from .candles import Bar
from .detector_v1 import DetectorV1

PREREGISTRO_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "pos-runner-v3"
    / "PREREGISTRO_ENTRADA_SUPORTE_2026-11-12.md"
)
META_KEY_HASH = "entrada_suporte_preregistro_hash"


class PreregistroAlteradoError(RuntimeError):
    """O texto do pre-registro em disco nao bate com o hash registrado -- recusa calcular/persistir."""


def hash_do_preregistro(path: Path = PREREGISTRO_PATH) -> str:
    return short_hash(path.read_text(encoding="utf-8"))


def garantir_entrada_suporte_registrada(storage: Any, path: Path = PREREGISTRO_PATH) -> str:
    """1a chamada registra o hash atual do pre-registro; chamadas seguintes recusam
    (`PreregistroAlteradoError`) se o arquivo em disco mudou depois do registro -- mesma disciplina
    de `saida_fiel.garantir_saida_fiel_registrada` (nunca editar um pre-registro no meio da coleta)."""
    atual = hash_do_preregistro(path)
    registrado = storage.get_meta(META_KEY_HASH)
    if registrado is None:
        storage.set_meta(META_KEY_HASH, atual)
        return atual
    if registrado != atual:
        raise PreregistroAlteradoError(
            f"docs/pos-runner-v3/PREREGISTRO_ENTRADA_SUPORTE_2026-11-12.md mudou depois de registrado "
            f"(registrado {registrado}, atual {atual}) -- abra uma nova emenda datada, nunca "
            "reescreva o pre-registro em silencio."
        )
    return atual


@dataclasses.dataclass(frozen=True)
class RevisitaSuporte:
    idx: int             # candle da revisita -- decisao no FECHAMENTO deste indice
    low: float
    s_no_momento: float  # S/fundo da caixa no momento (replay incremental, nunca o valor final)
    stop: float          # S_no_momento x (1 - stop_below_wick_pct) -- MESMA formula oficial


def localizar_revisitas_suporte(bars: list[Bar], tf: str, l_bc: Optional[float],
                                created_ts: Optional[float], params: Any, zona_alvo: int,
                                gatilho_idx: int) -> list[RevisitaSuporte]:
    """Reexecuta `DetectorV1` 0..`gatilho_idx-1` e devolve TODAS as revisitas ao suporte (passo 3 do
    pre-registro) da MESMA zona do sinal real, apos a caixa ter se tornado WATCHLIST (armada) e antes
    do gatilho. Lista vazia = sinal NAO ELEGIVEL para esta hipotese (nunca inventa uma revisita)."""
    det = DetectorV1(params, tf, l_bc, None, created_ts)
    i_watchlist: Optional[int] = None
    revisitas: list[RevisitaSuporte] = []
    tocando = False
    for i, bar in enumerate(bars):
        if i >= gatilho_idx:
            break
        eventos = det.update(bar)
        for ev in eventos:
            if ev.kind == "WATCHLIST" and ev.data.get("zona") == zona_alvo:
                i_watchlist = i
        if i_watchlist is None or i <= i_watchlist:
            continue
        if det.zone is None or det.zone.zid != zona_alvo:
            continue
        region = det.zone.S * (1.0 + params.test_zone)
        if bar.low <= region:
            if not tocando:
                stop = det.zone.S * (1.0 - params.stop_below_wick_pct)
                revisitas.append(RevisitaSuporte(idx=i, low=bar.low, s_no_momento=det.zone.S, stop=stop))
            tocando = True
        else:
            tocando = False
    return revisitas
