# Diagnóstico 2026-11-10 — carteiras "pro" (H8/H9): `RateLimited` com orçamento mostrando 0/600

PEDIDO 2026-11-10 (rodada 15, Parte 1, autorizado). **SOMENTE LEITURA — zero código alterado nesta
parte.** Sintoma reportado: `saude.py` mostra "snapshots nas últimas 24h: 0", "orçamento hoje: 0/600"
e "último erro: RPC exhausted: `getTokenLargestAccounts`: 6 tentativas sem resposta (RateLimited)".

## 1) RPC/plano e limite real

`worker.py` constrói o cliente RPC assim: `SolanaRpc(endpoints_from_env(), per_min=40, timeout_s=20,
max_attempts=6)`. `endpoints_from_env()` (env `POS_RUNNER_RPC_URLS`) cai no default
`DEFAULT_ENDPOINTS = ("https://api.mainnet-beta.solana.com",)` quando a env não está configurada —
ou seja, **1 único endpoint público e gratuito**, salvo o operador ter configurado um RPC pago na VM
(sem evidência disso no código; a confirmar com o operador se um `POS_RUNNER_RPC_URLS` próprio existe
na VM real).

- **req/min efetivo**: `per_min=40` é o TETO (`RateLimiter`, token bucket + AIMD). Cada 429 CORTA o
  ritmo pela metade, com piso `min_per_min=20.0` (hardcoded em `SolanaRpc.__init__`) — ou seja, o
  ritmo efetivo pode cair pra **20 chamadas/min (0,33/s)** depois de alguns 429s, e só sobe de volta
  aos poucos por sucesso (AIMD, `recover_per_success=0.5` fichas/sucesso).
- **req/mês**: nenhum teto de plano configurado no código para o endpoint público (`DAILY_LIMIT_CODE`
  só existe para planos PAGOS que devolvem esse código específico de erro) — o público só devolve
  HTTP 429 genérico, tratado como rate-limit comum (recuo AIMD), nunca um "limite diário do plano".
- **tentativas/teto de parede**: `max_attempts=6` (bate exatamente com "6 tentativas sem resposta" do
  log) e `max_total_wait_s=30.0` (default da classe, não sobrescrito em `worker.py`) — a chamada
  inteira desiste em 30s de parede OU 6 tentativas, o que vier primeiro.

## 2) Quantos pools a coleta tenta por ciclo

`_carteiras_elegivel` (linha ~1666 de `live.py`): elegível = posição ABERTA (V1 ou V2) **OU** fase
atual runner/pullback (V1 ou V2). Cada pool elegível, 1x por hora UTC (bucket), dispara
`_atualizar_carteiras_horaria` → `adapter.holders()` → **até ~22 chamadas RPC sequenciais** (1x
`getTokenLargestAccounts` + 1x `token_supply` + até 20x `getAccountInfo`, 1 por maior holder). Com N
pools elegíveis na mesma hora, são até `22×N` chamadas competindo pelo MESMO `per_min=40` — o teto é
por hora de relógio, não por pool.

## 3) Política de retry/backoff

`RateLimiter` é AIMD por endpoint (token bucket `per_min`/`burst`, pausa de 429 crescente até
`pause_max_s`). `SolanaRpc.call_raw` roda até `max_attempts` tentativas, cada uma esperando no máximo
`max_wait_s=20.0` no limitador, com a chamada INTEIRA desistindo em `max_total_wait_s=30.0`. Isto é
um circuit-breaker correto (BUG PRIORITÁRIO 2026-10-22) — mas o teto de 30s de parede é **matematicamente
apertado** mesmo SEM nenhum 429 real: 22 chamadas sequenciais, com `burst=4` livres e as 18 restantes
esperando ~1,5s cada no limitador (`60s/40 chamadas`), já somam **~27s só de espera no limitador**,
antes de contar a latência de rede de cada chamada — ou seja, mesmo um endpoint saudável e sem rate
limit algum deixa pouca margem pra completar as ~22 chamadas de 1 snapshot dentro do teto de 30s.
Qualquer 429/latência real empurra isso pra fora do teto — explica por que `getTokenLargestAccounts`
(a 1ª chamada da sequência) já falha sozinha depois de 6 tentativas quando o limitador compartilhado
já está degradado (AIMD no piso de 20/min) por tráfego concorrente no MESMO endpoint.

## 4) O contador de orçamento está medindo errado (causa direta do "0/600")

`_registrar_snapshot_carteiras` (linha ~3174 de `live.py`) **só grava uma linha em
`pr_carteiras_snapshot` quando `holders.tag != "holders_indisponivel"`** — ou seja, só em SUCESSO.
`saude.py` lê `usado_hoje = storage.pr_carteiras_snapshot_count_since(inicio_do_dia, "horaria")` e
mostra isso como "orçamento hoje: {usado_hoje}/{carteiras_max_chamadas_dia}". **Esse contador conta
SUCESSOS, nunca tentativas.** Com toda tentativa falhando (RateLimited), o contador fica
permanentemente em 0 — e o CHECK de orçamento em `_atualizar_carteiras_horaria`
(`if ... >= self.carteiras_max_chamadas_dia: ... return`) nunca dispara, porque também lê o mesmo
contador de sucessos. **O bot nunca se autolimita por volume de tentativa/falha** — ele tenta de novo
em TODO pool elegível, toda hora, pra sempre, mesmo que 100% das tentativas da última hora tenham
falhado.

## 5) RPC compartilhado com funções críticas

`worker.py` cria **1 único** `SolanaRpc` e passa o MESMO objeto pra `LineageVerifier` (verificação de
graduação/linhagem, crítica pra admissão/acompanhamento de pools em TODAS as versões V0-V3) e pra
`SolanaAdapter` (usado por `carteiras_pro.holders()`). Os dois competem pelo MESMO `RateLimiter` por
endpoint — uma tentativa de snapshot de carteiras "pro" falhando/retentando consome o MESMO orçamento
de 40/min que a detecção de graduação/linhagem precisa.

## Causa provável (resumo)

1. Endpoint único, gratuito, `per_min=40` (piso AIMD 20/min) — compartilhado com lineage/graduação.
2. Cada snapshot horário custa ~22 chamadas sequenciais, matematicamente apertado contra o teto de
   parede de 30s mesmo sem rate-limit real; com múltiplos pools elegíveis na mesma hora, o endpoint
   degrada (AIMD) e passa a falhar logo na 1ª chamada da sequência.
3. O contador de orçamento (`pr_carteiras_snapshot_count_since`) só soma SUCESSOS — "0/600" não
   significa "zero tentativas", significa "zero sucessos"; o bot nunca reduz a frequência de
   tentativa mesmo com 100% de falha.

## Opções de correção (nenhuma implementada nesta parte — ver Parte 2)

- **(a) Fila com taxa fixa dedicada**: orçar a coleta de carteiras com seu PRÓPRIO limitador/fila
  (nunca o mesmo `RateLimiter` por endpoint que lineage/graduação usa), com uma taxa deliberadamente
  baixa e fixa (nunca AIMD-degradável pelo tráfego de OUTRA função).
- **(b) Prioridade absoluta pra pools com sinal/posição aberta recém-disparado**: snapshot no
  INSTANTE do alerta (gravado com timestamp), nunca esperando o próximo bucket de hora — hoje a
  snapshot de ENTRADA já reusa uma chamada existente (zero custo extra), mas não é priorizada sobre a
  coleta horária no mesmo ciclo.
- **(c) Cache por pool / contar tentativas, não só sucessos**: o contador de orçamento devia refletir
  TENTATIVAS (sucesso + falha), pra autolimitar de verdade quando o endpoint está degradado, em vez
  de ficar cegamente em 0 e tentar pra sempre.

A opção escolhida e implementada está na Parte 2 desta rodada.
