"""POS-RUNNER-V0 — estrategia "pos-runner" (PAPER / somente leitura).

Fases: 0 pre-migracao -> 1 runner forte -> 2 queda de 80-90% e consolidacao acima do nivel da
curva (L_bc) com pavios testando o suporte -> 3 rompimento da caixa = entrada.

Este pacote nao executa ordens, nao usa chave privada e nao assina transacao. O mesmo detector
causal serve ao backtest (Parte A) e ao bot ao vivo (Parte B). Hipotese registrada em
`docs/research-hypothesis-registry-v1-2026-10-04.md` (ID POS-RUNNER-V0).
"""
