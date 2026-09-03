# Crypto Copy Trader — Project Context

Este arquivo registra o estado técnico consolidado do projeto. Ideias discutidas fora do código são hipóteses até serem confirmadas por implementação, testes e evidência reproduzível.

## Estado atual

- Branch de pesquisa principal: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Nenhum fluxo liberado assina, envia ou executa transações reais.
- Persistência principal: SQLite via `DATABASE_PATH` (padrão `data/copytrader.db`).
- Wallet Forward v2 encerrou a replicação Run 1 × Run 2.
- Classificação final pré-registrada: **OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**.
- **Não iniciar Run 3 automaticamente.**
- Próximo gate selecionado: **Causal Opportunity Acquisition v1**.
- Opportunity Snapshot Core v1 existe em branch de validação, com causalidade dual-clock e anti-leakage.
- Última suíte confirmada após os fixes pós-Run2: **459 testes, zero falhas**, com `compileall` aprovado.

## Regra central

```text
IMPLEMENTADO
-> TESTADO
-> VALIDADO OPERACIONALMENTE
-> EVIDÊNCIA ECONÔMICA
-> SHADOW EXECUTÁVEL
-> LIVE CANARY
```

Código funcionando não prova edge. Quote não prova fill. Backtest positivo não libera live. Nenhum score, wallet ou feature é promovido sem causalidade, cobertura, missingness, dependência, custos e validação forward adequados.

## Tese de pesquisa atual

O projeto não está mais preso à hipótese de que `wallet -> copiar` seja suficiente.

A direção atual é construir um **Solana Opportunity Intelligence / Opportunity Engine**, em que wallets são um canal de informação entre vários:

1. execução / liquidez / tradability;
2. order flow / microestrutura;
3. token-risk / manipulação / hazard rejection;
4. wallet action intelligence + independência;
5. market/regime context;
6. price/momentum/reversal;
7. launch/lifecycle intelligence venue-agnostic;
8. graph/relationship intelligence;
9. social/attention apenas se provar valor incremental.

Pump.fun, X/social, wallets e Wave não são pilares obrigatórios. Cada canal deve provar utilidade incremental.

North star:

> identificar oportunidades cujo resultado forward, ajustado por risco, custos e executabilidade realista, permaneça favorável em janelas independentes.

## Evidência externa registrada

Documentos principais:

- `docs/research-signal-universe-v1-2026-09-02.md`
- `docs/research-evidence-registry-v1-2026-09-02.md`
- `docs/post-run2-evidence-decision-framework-2026-09-02.md`

A literatura pesquisada favorece priorizar order flow, liquidez, microestrutura, risco, regime e execução antes de adicionar social/NLP complexo. Modelos simples continuam candidatos fortes; deep learning não é objetivo por si só.

## Wallet Forward runtime atual

Runtime validado:

`wallet_forward_runtime_v5_enrollment_followup_rotating_poll_confirmed_commitment`

Características:

- bootstrap causal;
- polling rotativo;
- commitment `confirmed` com auditoria posterior de finality;
- resiliência RPC e fallback;
- telemetry persistida de failures/recovery;
- run manifest imutável;
- bloqueio de runs ACTIVE sobrepostas;
- enrollment econômico congelado;
- follow-up observacional separado;
- quote child + wallet child alinhados;
- grace/drain para quotes agendadas;
- Jupiter read-only;
- sem private key / assinatura / `/execute`.

Network Resilience Gate: **APPROVED**.

## Wallet Forward acquisition v2

Universo público congelado:

`wallets/research-cohort-public-v2-2026-09-02.txt`

- 27 endereços candidatos.
- Sync uniforme de 6 páginas.
- Sem uso de PnL/win rate/return/profit factor para eligibility/ranking.

Coorte forward v2 congelada:

1. `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`
2. `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`
3. `2RssnB7hcrnBEx55hXMKT1E7gN27g9ecQFbbCc5Zjajq`

Acquisition v2 gate: **PASSED**.

## Wallet Forward v2 — Run 1

Run key:

`wallet-forward-1788360461-8a3986f9`

Protocol:

- COMPLETED;
- 10h00m04s;
- enrollment 4h;
- follow-up 6h;
- polling 10s;
- confirmed;
- Jupiter proxy quotes;
- delays 0/15/30/60/120s;
- notional US$25.

Observed:

- 15 actions;
- 9 BUY / 6 SELL;
- 4 enrolled BUYs;
- 5 follow-up-only BUYs corretamente excluídos do denominador;
- finality 15/15;
- causal boundary clean;
- BUY quote readiness 45/45 attempts successful;
- 2/3 wallets ativas;
- forte dependência: 3/4 enrolled BUYs no mesmo wallet×token cluster.

### Quantity-aware replay

A persistência de quantidade revelou que três BUYs `5TVs...` da mesma wallet foram liquidados por um único SELL completo. O replay antigo de um SELL por lote era economicamente incorreto.

Replay corrigido:

| Delay | Closed | Censored | Mean net | Median net | Win rate | PF |
|---|---:|---:|---:|---:|---:|---:|
| +0s | 3 | 1 | -28.76% | -40.40% | 33.3% | 0.0060 |
| +15s | 3 | 1 | -30.37% | -45.76% | 33.3% | 0.0148 |
| +30s | 0 | 4 | n/a | n/a | n/a | n/a |
| +60s | 3 | 1 | -25.36% | -33.61% | 33.3% | 0.0376 |
| +120s | 0 | 4 | n/a | n/a | n/a | n/a |

Interpretação obrigatória: isto é **DESCRIPTIVE**, não “estratégia perde 30%”. A amostra é pequena e altamente dependente.

Quantity-Aware Accounting Gate: **PASSED**.

## Wallet Forward v2 — Run 2

Run key:

`wallet-forward-1788400735-5cbe70af`

Protocol idêntico ao Run 1.

Observed:

- COMPLETED;
- 10h00m07s;
- 3 forward actions;
- 0 BUY / 3 SELL;
- enrollment cutoff com **0 BUYs enrolled**;
- 0 RPC sync/capture failures;
- 0 bootstrap failures;
- 0 RPC recoveries;
- finality **3/3 finalized success**, 0 missing/error.

Run 2 não tem amostra econômica. Ele não confirma nem refuta os retornos descritivos do Run 1.

Documento final:

`docs/wallet-forward-v2-run1-run2-final-decision-2026-09-03.md`

## Decisão Run 1 × Run 2

As duas runs somam 20h nominais de observação, mas apenas 4 BUYs enrolled, todos no Run 1, e 75% deles no mesmo wallet×token cluster.

Classificação pré-registrada final:

**OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**

Consequências:

- não afirmar edge wallet-only;
- não afirmar falha definitiva wallet-only com base no P&L pequeno;
- não retunar delays/coorte usando o resultado;
- não lançar Run 3 automaticamente;
- não promover shadow/live;
- qualquer redesign de aquisição precisa de protocolo novo pré-registrado.

## J8PS — horizonte maior que a janela

Um BUY `J8PS...` da `7mP...` ficou right-censored no endpoint do Run 1.

Run 2 observou posteriormente a liquidação integral da quantidade exata, aproximadamente 19h depois da detecção original.

Esse SELL não é adicionado retroativamente ao P&L do Run 1. Ele apenas mostra que uma janela de 10h pode censurar estratégias/arquétipos de holding mais longos.

## Fixes descobertos no closeout

### 1. Exact quote identity

O CLI antigo de replay poderia associar `quote_key` e quote pela posição de duas listas com ordenações diferentes.

O caminho novo resolve cada quote pela identidade exata da chave.

A correção não alterou os números consolidados do Run 1, mas remove uma fonte real de associação incorreta.

### 2. Cross-run SELL quote lineage

O quote watcher podia usar BUY quotes de uma run antiga para criar SELL probes em uma run posterior da mesma wallet/token.

Regra corrigida:

> SELL lineage só pode reutilizar BUY quote cujo source observation possua a mesma `run_key`.

Isso impede consumo de provider e logs cross-run enganosos.

### 3. Logging side-aware

O watcher imprimia `[wallet buy]` até para eventos SELL. O log agora imprime o side persistido explicitamente.

## Opportunity Snapshot Core v1

Arquivos principais:

- `src/opportunity_snapshot_core.py`
- `tests/test_opportunity_snapshot_core.py`
- `docs/opportunity-snapshot-core-v1-design-2026-09-02.md`
- `docs/opportunity-core-review-2026-09-03.md`

Contrato causal:

- `chain_time/event_time` representa quando o mercado aconteceu;
- `observed_at` representa quando o bot ficou sabendo;
- uma row só entra em uma feature se pertence à janela de mercado **e** estava disponível até o cutoff;
- quotes preservam freshness/age;
- missingness fica explícita;
- `decision_as_of` deve incluir o tempo gasto para obter as próprias features.

Nenhum score automático de trading foi implementado.

## Data-source feasibility

Documento atual:

`docs/opportunity-data-source-feasibility-v2-2026-09-03.md`

Stack inicial preferida para pesquisa:

- Wallet/on-chain trigger: infraestrutura RPC existente;
- execution proxy: Jupiter;
- short-window flow: Birdeye, se cobertura/custo forem validados;
- raw microstructure: Solana Tracker se créditos estiverem operacionais, com fallback de desenho para outras fontes;
- network regime: Solana RPC priority-fee context.

Nova integração paga não deve ser adicionada sem necessidade comprovada.

## Próximo gate — Causal Opportunity Acquisition v1

Protocolo pré-registrado:

`docs/causal-opportunity-acquisition-v1-protocol-2026-09-03.md`

Objetivo: resolver a escassez de amostra sem transformar as 3 wallets anteriores em parâmetros ajustados por resultado.

Desenho inicial:

- trigger universe: 27 wallets públicas já existentes no universo v2;
- todas servem como fontes observacionais, não como portfólio de cópia;
- cada novo BUY vira raw trigger;
- mesmo token dentro de 60s pertence ao mesmo opportunity episode para evitar enrichment duplicado, mas raw events continuam preservados;
- Opportunity Core captura wallet state + execution + flow + regime + basic risk quando causalmente disponível;
- `decision_as_of` é congelado depois da disponibilidade das features obrigatórias;
- outcomes ficam separados das features;
- labels exploratórios: +5m/+15m/+60m;
- primeira janela: 12h;
- se insuficiente, uma única segunda janela idêntica antes de novo redesign.

Data-readiness targets do primeiro gate:

- zero look-ahead;
- >=30 opportunity episodes;
- >=15 tokens;
- >=5 source wallets;
- maior wallet <=50% dos episodes;
- maior token <=20%;
- >=90% dos episodes com identity/timing + execution proxy utilizável.

Passar este gate valida aquisição de dados, não edge.

## Social / Pump / graph

- Social/X não é prioridade Core v1.
- Pump.fun/PumpSwap permanece integrado como venue/on-chain source, mas não recebe privilégio metodológico.
- Graph/funding lineage pode subir de prioridade se convergência multi-wallet se tornar central.
- Nenhuma feature social, narrativa ou graph deve virar regra de BUY sem ablation incremental.

## Shadow / live

Estado atual:

- causal forward infrastructure: forte;
- quantity-aware accounting: validado;
- wallet-only edge: **não estabelecido**;
- multissignal Opportunity Intelligence: em construção;
- executable fill/landing: não validado;
- shadow executável: não liberado;
- live: não liberado.

O projeto continua explicitamente **PAPER / RESEARCH / READ ONLY**.
