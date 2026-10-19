# Emenda de qualidade de dados — PROPOSTA (não aplicada)

Status: **PROPOSTA, cega a resultado** (nenhum trade/EV calculado com estas regras). Nada neste documento foi
aplicado a `Params`, `pipeline.py`, ao checkpoint ou ao selo do holdout. Depende de revisão e OK explícito do
operador antes de qualquer commit de código.

## 0. Evidência (checkpoint do operador, discovery, 2026-10-19)

Diagnósticos 2/3 (`docs/pos-runner-v0-handoff-2026-10-19.md`, `mc_auditoria.py`) confirmaram: **nossa conversão
preço→MC está correta** (`fator ≈ 1,00` contra o GT, auditado em pools reais). O defeito é o candle histórico do
próprio GT em pools Meteora DBC: picos de 1 candle (razão `high/close` até ~4×10⁹) e preço do 1º candle
pós-graduação absurdo (US$0,12–US$3,86/token, supply ~1 bi). Não é um bug nosso — é um defeito de dado
upstream, que precisa de um filtro de qualidade, não de uma correção de fórmula.

L_bc por faixa (`stage1.l_bc`, discovery):

| faixa | DBC (917) | pump.fun (132) |
|---|---|---|
| < US$1k | 117 | 47 |
| US$1k–20k | 87 | 9 |
| US$20k–500k | 166 | 76 |
| US$500k–10M | 253 | 0 |
| > US$10M | 294 | 0 |

Todo pool com `L_bc >= 500k` vira "runner" automaticamente pelo piso absoluto de 300k — **547/917 (60%) dos
"runners" DBC atuais são, no mínimo, suspeitos**.

## 1. `dado_invalido` — gate de qualidade (nunca econômico)

| critério | valor proposto | por quê é objetivo |
|---|---|---|
| wick do 1º candle real | `high/close >= 3,0` | propriedade do candle, igual em qualquer launchpad; não referencia EV/trade |
| `L_bc` (robusto, item 3) | `< US$100` | precisão/pool morto — nenhuma graduação real tem L_bc abaixo disso |

Sem teto fixo de L_bc por launchpad: pump.fun tem curva fixa (~US$40–70k, bate com os 28–51k medidos em
16/10), mas a DBC é configurável por projeto — um teto pump.fun-específico penalizaria DBC legítima só por
ser DBC. O teste de wick já cobre o defeito observado sem precisar desse teto.

```python
# params.py (diff, NAO aplicado)
candle_wick_ratio_max: float = 3.0
l_bc_floor_usd: float = 100.0

# pipeline.py stage1() (diff, NAO aplicado) -- apos `real = [...]` nao vazio:
first = real[0]
wick_ratio_1o = (first.high / first.close) if first.close else float("inf")
l_bc = min(first.open, first.close, real[1].open if len(real) > 1 else float("inf"))
if wick_ratio_1o >= ctx.params.candle_wick_ratio_max or l_bc < ctx.params.l_bc_floor_usd:
    ctx.store.save_stage1(row["pool"], "dado_invalido", None, None, l_bc, supply,
                          {"motivo": "wick" if wick_ratio_1o >= ctx.params.candle_wick_ratio_max else "l_bc_floor",
                           "wick_ratio_1o": wick_ratio_1o})
    return "dado_invalido", None
```

**24 combinações**: inalteradas (muda a população que entra no funil, não a grade). **Hash**: `Params` ganha
2 campos → `versao_config` muda.

## 2. Runner por fechamento (robusto a wick de 1 candle)

```python
# pipeline.py stage1() (diff, NAO aplicado)
max_mc = max(b.high for b in real)                               # continua gravado (atributo "extremos")
runner = max(b.close for b in real) >= ctx.params.runner_min_mc  # era max_mc >= ...
```

Só a fase 1 ("é runner?") muda para fechamento. Fase 2+ (zona/queda/teste/entrada) continuam com
`queda_medida` extremos/fechamentos exatamente como já registrado (§10) — não duplica essa dimensão.
**24 combinações**: inalteradas. **Hash**: novo campo `runner_gate_by_close: bool = True` → `versao_config`
muda.

## 3. L_bc robusto (embutido no diff do item 1)

`min(open, close do 1º candle, open do 2º)` em vez de `open` isolado. Efeito direto: `S >= 0,75×L_bc` fica
**mais fácil** de passar (L_bc menor) — consequência de remover um defeito, não um ajuste de resultado;
declarado aqui de propósito, não escondido.

## Reprocessamento se aplicado

`versao_config` muda (campos novos) → **não é um restamp** (a interpretação do dado muda, não só a etiqueta):
`stage1`/`stage2`/`setups`/`trades` de todos os pools já processados precisam recomputar do zero — nada se
perde, o que existe hoje já está contaminado pelo defeito. **Holdout selado continua válido** (enumeração
on-chain não depende de `Params`).

## 4. Projeção (script `projecao_emenda.py`, entregue separadamente)

Não tenho o checkpoint do operador — o script roda do lado dele, sem rede, sem escrever no banco, e projeta:
pools válidos, runners (regra antiga vs nova) por launchpad, setups 1h projetados para o discovery inteiro
(pela taxa `setups_primários/runner_válido` já medida nos pools processados) e para o holdout (27.349
graduações seladas: pump.fun 9.075, Meteora DBC 17.861, Raydium LaunchLab 413), usando a MESMA taxa medida no
discovery como proxy (holdout ainda não processado).

```powershell
git pull
python signals_mvp\pos_runner\parte_a\projecao_emenda.py --repo . --periodo discovery
```
