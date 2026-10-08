# Opção H — Memecoins Estabelecidas, Momentum — Discovery V0 — Preregistration — DRAFT — 2026-10-08

Status: **DRAFT — aguarda sign-off do operador. Não autoriza nenhum backtest, nenhuma consulta a
outcome, nenhuma coleta.** Escrito antes de olhar qualquer retorno/direção dos dados que vai
julgar. Commit precisa acontecer e o sign-off precisa ser dado antes de rodar qualquer código deste
protocolo.

ID no registro: `MOVE-FIRST-H-DISC-V0`. Fonte da opção: `docs/strategy-options-move-first-2026-10-07.md`,
Opção H, revisão 3.

## Por que isso existe agora

A revisão 3 do memo de opções escolheu H e G como os 2 caminhos da rodada. H vem primeiro porque é
observacional (sem gatilho de entrada, sem execução) e não depende de nada travado no programa
(nem da replicação do PQ-TR, nem de merge de branch). Este documento é só o **discovery** — gera
no máximo 1 candidato, não valida nada (regra 4 do registro de hipóteses). Uma confirmação
prospectiva separada (`MOVE-FIRST-H-CONF-V0`, não escrita ainda) julga o candidato depois.

## O que NÃO é

- não é a confirmação — não promove nada a `VALIDADA` nem decide se o programa continua;
- não abre execução, não autoriza ordem real, não toca em capital;
- não reinterpreta nenhum resultado fechado (V48/V55/V68/PQ-V1/CD-V0/CD-PROMO-V0 permanecem como estão);
- não compartilha amostra com nenhuma hipótese de minuto-inicial — universo, horizonte e mecanismo são outros.

## 1. Correção de escopo em relação ao memo (ler antes do resto)

O memo (revisão 2) descrevia isto como "backtest histórico puro, sem coleta nova". Verificado e
**corrigido na revisão 3**: nem GeckoTerminal (`src/prices.py`) nem Birdeye (`src/discovery/birdeye.py`),
os dois providers já integrados neste repositório, dão um arquivo histórico de "que tokens
existiam/tinham liquidez numa data passada, incluindo os que já morreram" — GeckoTerminal "New
Pools" olha só ~48h antes de agora; Birdeye `new_listing` olha só ~3 dias. Nenhum dos dois serve
pra reconstruir 3 semanas atrás sem viés de sobrevivência.

**Decisão proposta para V0 (pendente do seu sign-off — seção 11):** usar só a **captura causal
própria** deste repositório como fonte do universo. Ela observa toda criação/graduação de token
desde **2026-08-20** (confirmado via `git log --reverse`), sem filtrar por "sobrevivente atual" —
livre de viés de sobrevivência por construção, mesmo sendo uma janela curta (~7 semanas até hoje).
Um backfill on-chain mais profundo (ler histórico de slots/transações anterior a 2026-08-20) fica
**fora de escopo da V0** — se a amostra desta V0 for insuficiente, a saída honesta é classificar
`INCONCLUSIVE_SAMPLE` (mesmo precedente de `DEPLOYER-V0`/`CHURN-PROSP-V1`), não esticar o escopo
no meio do protocolo.

## 2. Universo ("estabelecida", critérios candidatos — confirmar no sign-off)

Um token entra no universo de uma data de rebalanceamento `t` se, **usando só dado anterior a `t`**:

1. já graduou da bonding curve para PumpSwap há **>= 7 dias de calendário** antes de `t` (margem
   larga sobre os dois achados de risco de entrada precoce: MemeTrans — ~73% dos tokens caem para
   <40% do preço de migração em 20min — e E12 — >85% dos snipers saem em <5min; 7 dias deixa as
   duas janelas de risco muito atrás);
2. teve volume 24h >= **US$5.000** (placeholder, a confirmar) em pelo menos 5 dos 7 dias de
   calendário imediatamente antes de `t`;
3. tem preço resolvível em `t` (não está morto/sem liquidez a ponto de não existir cotação).

## 3. Sinal (só momentum na V0 — atenção fica fora, exige pipeline próprio não construído)

Feature única: retorno acumulado nos **N dias anteriores a `t`** ("momentum"), mesma lógica de
Liu/Tsyvinski/Wu (JF 2022) — ordenação cruzada semanal, quintil de maior momentum vs quintil de
menor. **Long-only**: o programa não tem infraestrutura de short/borrow para memecoin, então não
replicamos o lado short do paper — divergência de escopo registrada aqui, não escondida.

## 4. Rótulo e horizonte

Retorno forward de **7 dias de calendário** a partir de `t` (próximo rebalanceamento semanal). Não
colide com nenhum horizonte congelado em segundos (`ROUTE_RESEARCH_HORIZONS_SECONDS` é sobre
outro sistema, outra unidade, outra pergunta).

## 5. Comparações desta descoberta (registradas antes, não escolhidas depois de ver o resultado)

Varredura de **4 combinações**, todas pré-registradas aqui:

| Lookback (N dias) | Piso de volume 24h |
|---|---|
| 7 | US$5.000 |
| 7 | US$20.000 |
| 14 | US$5.000 |
| 14 | US$20.000 |

Isso é **discovery** (regra 4 do registro): gera no máximo 1 candidato; não promove nada a
`VALIDADA`. Candidato = a combinação com maior separação de direção consistente (ver seção 6).

## 6. Split temporal dentro da própria descoberta (fora da amostra, mesmo em discovery)

Mesma disciplina de calendário do E11 (70%/15%/15%, mas aqui simplificada para 70/30 dado o
tamanho pequeno da amostra): os primeiros **70% dos dias de calendário** da janela de captura
(2026-08-20 até o corte desta descoberta) servem para **escolher** a combinação candidata da
seção 5. Os últimos **30%** são um retentor temporal: a combinação candidata só é promovida à
confirmação se a direção do retentor **concordar em sinal** com a direção do treino (não precisa
bater em magnitude, só não inverter). Combinação que inverte de sinal no retentor não é promovida
— vira `INCONCLUSIVE`, sem escolher outra combinação pra substituir (isso seria retunar depois de
ver o dado).

## 7. Custo e slippage escalados por liquidez (não um bps fixo)

Para cada posição simulada, custo de ida+volta estimado por:

```
impacto_pct ≈ (tamanho_posicao_usd / (2 × liquidez_do_pool_usd)) × 100   # aproximação de produto constante, pequena ordem
custo_ida_volta_pct ≈ 2 × impacto_pct + 0,25%   # 0,25% = fee de swap PumpSwap, confirmada em 3 fontes (ver memo)
```

`liquidez_do_pool_usd` lida no momento de `t` (não um número fixo global) — é a mesma disciplina
de "regra, não número" já usada no Gate 2 do PQ-TR para preço do SOL/ATA. Sweep de 1x/2x sobre
este custo, mesma disciplina do Gate 2 (`docs/participant-quality-tail-risk-gate2-cost-preregistration-DRAFT-2026-10-07.md`).

## 8. Suporte mínimo e classificação

- Suporte mínimo: **n >= 30 observações token-semana** no quintil de maior momentum, somando as 2
  metades do split temporal. Abaixo disso: `INCONCLUSIVE_SAMPLE_NO_EXTENSION` (mesmo precedente de
  `DEPLOYER-V0`), sem esticar a janela de captura além de 2026-08-20 nem importar backfill no meio
  do protocolo.
- `DISCOVERY_MOVE_FIRST_H_V0_CANDIDATE`: exatamente 1 combinação concorda em sinal entre treino e
  retentor E atinge o suporte mínimo — essa combinação, sozinha, vai para `MOVE-FIRST-H-CONF-V0`
  (a escrever depois, como confirmação prospectiva fresca, horizonte/corte congelados, sem retune).
- `INCONCLUSIVE_NO_CANDIDATE`: nenhuma combinação concorda em sinal, ou nenhuma atinge suporte
  mínimo — fecha a V0, sem promover nenhuma combinação, sem tentar outro lookback/piso fora da
  tabela da seção 5.

## 9. Risco de transferência (explícito, não escondido)

A evidência acadêmica mais forte citada no memo para H (Liu & Tsyvinski, RFS 2021; Liu/Tsyvinski/Wu,
JF 2022) vem de BTC/XRP/ETH ou do top-1500 de criptomoedas por market cap, **2011-2018**, com
rebalanceamento semanal. Memecoins Solana "estabelecidas" (graduadas há 1-2 meses, em 2026) são
uma população, era de mercado e microestrutura diferentes. Mecanismo (momentum via quem compra
tarde/vende cedo numa tendência) é o mesmo tipo de efeito, mas a transferência não é automática —
exatamente a mesma ressalva que o registro já aplica a E2-E6. Este discovery é o teste dessa
transferência, não a prova dela.

## 10. Proibições explícitas desta V0

- não compara com nenhuma hipótese de minuto-inicial (família CHURN/BUY-ACCEL/EARLY-BAL-CONC é
  outro mecanismo/população/horizonte — a razão exata pela qual H não é a mesma família);
- não troca lookback/piso de volume depois de ver a direção de nenhuma das 4 combinações;
- não estende a janela de captura com backfill no meio do protocolo;
- não promove mais de 1 combinação candidata;
- não abre execução nem toca em capital.

## 11. Pendências para o sign-off (minhas perguntas, não decisões já tomadas)

1. Piso de volume 24h: US$5.000/US$20.000 ficam como estão, ou outro valor?
2. Fonte do universo: só captura própria (2026-08-20+), como proposto na seção 1, ou autorizar
   também investigar backfill on-chain como tarefa de engenharia separada antes de rodar isto?
3. Tamanho de posição simulada para o cálculo de impacto (seção 7): US$25, igual ao resto do
   programa?

Nenhum destes itens foi decidido por mim — ficam explícitos para sua revisão antes do sign-off.
