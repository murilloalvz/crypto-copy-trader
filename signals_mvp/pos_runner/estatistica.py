"""RODADA 22 (2026-11-17, autorizada), condição 3 do operador: utilitário estatístico pequeno, só
stdlib, para a FUTURA regra de inviabilidade por prevalência do
`docs/pos-runner-v3/EMENDA_2026-11-16_CORRECAO_OWNER_CARTEIRAS.md` (§6.2d) -- o script de análise em
si (deltas/IC/placebo) continua sem implementar, igual ao `PREREGISTRO_CARTEIRAS_FORWARD_
2026-11-10.md` já declarava. Nunca entra em H1/N=30/N=60 nem em qualquer detector/sinal."""

from __future__ import annotations

import math


def wilson_ci(sucessos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confiança de Wilson (score interval) para uma proporção -- MUITO mais honesto
    que o normal/Wald em n pequeno ou p perto de 0/1 (nunca produz um limite fora de [0,1], nunca um
    intervalo de largura 0 quando sucessos==n ou ==0, ao contrário do normal/Wald). `z=1.96` =
    95% (padrão do projeto, mesma convenção dos outros ICs bootstrap já usados em `analise/
    condicional.py`). `n=0` -- dado ausente -- devolve o intervalo MAXIMAMENTE largo `(0.0, 1.0)`,
    nunca um ponto fabricado."""
    if n <= 0:
        return (0.0, 1.0)
    if not (0 <= sucessos <= n):
        raise ValueError(f"sucessos={sucessos} fora de [0, n={n}]")
    p = sucessos / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centro = p + z2 / (2.0 * n)
    margem = z * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))
    lo = (centro - margem) / denom
    hi = (centro + margem) / denom
    return (max(0.0, lo), min(1.0, hi))
