# Wallet Causal Replay v1

## Status

RESEARCH / READ ONLY. Esta camada não altera `wave_v3_volume_integrity`, não envia ordens e não afirma lucratividade de nenhuma wallet.

## Objetivo

Responder de forma causal à pergunta que separa Wallet Intelligence de uma eventual execução real:

> Depois que uma ação de wallet se torna observável para o nosso sistema, existe um quote utilizável cedo o bastante para simular uma execução sem look-ahead?

O replay v1 mede **observabilidade + disponibilidade de quote**. Ele ainda não mede edge completo nem reconstrói a estratégia inteira da wallet.

## Dois relógios obrigatórios

Cada ação forward já possui:

- `chain_time`: horário da ação na Solana;
- `observed_at`: horário em que nosso sistema realmente detectou a ação.

Cada quote causal passa a possuir:

- `market_time`: horário do estado de mercado representado;
- `observed_at`: horário em que nosso sistema realmente recebeu/registrou o quote.

O replay seleciona quotes por `observed_at`. Um preço histórico que represente um minuto antigo mas só seja consultado depois **não pode ser tratado como informação disponível no passado**.

## Quote executável x proxy

`CausalQuoteObservation.executable` separa duas classes de evidência:

- `True`: quote cuja fonte/semântica pode representar uma oportunidade executável sob as premissas do coletor;
- `False`: proxy de pesquisa, como candle ou outra referência que não garante rota executável.

Por padrão o replay exige quote executável. Proxies só entram com opção explícita e nunca contam como validação de execução live.

## Restrições causais v1

Para uma ação de wallet:

1. a ação precisa satisfazer `observed_at >= chain_time`;
2. `decision_ready_at = wallet_observed_at + decision_delay_seconds`;
3. um quote só pode entrar se `quote.observed_at >= decision_ready_at`;
4. o quote precisa chegar dentro de `max_quote_wait_seconds`;
5. `quote.observed_at - quote.market_time` precisa respeitar `max_quote_age_seconds`;
6. por padrão o quote precisa estar marcado como executável;
7. slippage é aplicado contra o replay: compra paga acima do market quote e venda recebe abaixo.

Essas regras evitam transformar sincronização posterior, candle histórico ou quote atrasado em fill artificialmente favorável.

## Componentes

- `src/causal_quotes.py`: modelo, validação e seleção do primeiro quote causal elegível;
- `src/causal_quote_store.py`: persistência SQLite idempotente;
- `src/wallet_causal_replay.py`: replay por ação e métricas agregadas;
- `causal_quote_ingest.py`: importador JSONL offline para snapshots já coletados;
- `wallet_causal_replay.py`: CLI de avaliação sobre ações forward + quotes persistidos.

## Delays padrão

A CLI avalia, por padrão:

```text
0s, 15s, 30s, 60s, 120s
```

O atraso acima é **adicional ao atraso real de detecção** já presente em `wallet_observed_at - chain_time`. Assim o relatório consegue separar:

- atraso da fonte/on-chain até nossa detecção;
- atraso de decisão configurado;
- espera pelo quote;
- atraso total `chain_time -> quote_observed_at`.

## Uso offline

Depois de existirem ações forward e quotes persistidos:

```powershell
python wallet_causal_replay.py
```

Para diagnóstico com proxies explicitamente marcados como não executáveis:

```powershell
python wallet_causal_replay.py --allow-proxy-quotes
```

Esse segundo modo é somente pesquisa de cobertura/timing. Não deve ser apresentado como evidência de preço executável.

Um arquivo JSONL externo também pode ser validado/importado:

```powershell
python causal_quote_ingest.py quotes.jsonl --dry-run
python causal_quote_ingest.py quotes.jsonl
```

Formato mínimo por linha:

```json
{"quote_key":"provider:id","token_mint":"...","market_time":123,"observed_at":124,"price_usd":0.01,"source":"provider_name","executable":true,"resolution_seconds":1}
```

`liquidity_usd` é opcional.

## O que v1 não faz

- não inventa quotes quando a tabela está vazia;
- não transforma `price_cache`/candles de 1 minuto em quotes executáveis;
- não calcula PnL de estratégia completa;
- não modela partial exits/staged exits da 7mPti;
- não estima market impact por tamanho da ordem;
- não confirma que a rota ainda estaria disponível no momento de submit;
- não assina nem envia transações.

## Próximo estágio

A próxima peça necessária é um coletor de **quotes realmente utilizáveis/executáveis**, persistindo `market_time`, `observed_at`, preço, liquidez/route context e fonte. Só depois faz sentido promover o replay de observabilidade para replay de edge/PnL e, posteriormente, shadow execution.
