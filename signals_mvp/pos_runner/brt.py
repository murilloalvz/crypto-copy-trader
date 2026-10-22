"""BRT (UTC-3) so para EXIBICAO (item 2.3/3.7 do PROMPT DEFINITIVO V1: "tudo em UTC; BRT so na exibicao").
Brasil nao observa horario de verao desde 2019 -- o deslocamento fica fixo, sem precisar de tabela de regras."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))


def hora_brt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=BRT).strftime("%H:%M")


def na_janela_ouro(ts: float, inicio: str, fim: str) -> bool:
    """Item 2.3: pela hora de FECHAMENTO do candle (quem chama passa o `ts` do fechamento), limites inclusivos."""
    return inicio <= hora_brt(ts) <= fim
