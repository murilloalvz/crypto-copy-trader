# Wallet Forward Watch — Plan 2026-08-31

## Status

RESEARCH / READ ONLY. Este plano não altera `wave_v3_volume_integrity`, não executa ordens e não usa a Solana Tracker Data API.

## Motivo

O deep scan cross-wallet produziu fingerprints descritivos úteis, mas ainda só uma wallet (`7mPti`) passou a gate de cobertura `evidence_ready`. Nenhuma assinatura apareceu em duas wallets com cobertura mínima.

Continuar aumentando backfill indiscriminadamente tem retorno informacional menor do que observar algumas wallets em tempo real e medir o atraso real `chain_time -> observed_at`.

Desde a versão inicial deste plano, a infraestrutura de Causal Replay e de route quotes foi preparada. Portanto o mesmo período forward pode, opcionalmente, produzir **duas camadas independentes de evidência**:

1. observabilidade da ação da wallet;
2. disponibilidade de uma rota cotada depois que a ação foi observada.

## Coorte forward v1

Arquivo:

```text
wallets/forward-watch-archetypes-2026-08-31.txt
```

Wallets:

1. `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`
   - referência comportamental mais madura;
   - `one_day | mixed_exit | occasional_reentry | moderate`;
   - 36 tokens, 72,2% de roundtrips e 21 ciclos complete-like no deep scan.

2. `Gf9XgdmvNHt8fUTFsWAccNbKeyDXsgJyZN8iFJKg5Pbd`
   - candidato distinto `ultra_short | single_exit_dominant | rare_reentry | moderate`;
   - boa diversidade de tokens, mas apenas 36,1% de roundtrips observados no histórico local.

3. `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`
   - candidato `ultra_short | staged_exit_dominant | frequent_reentry | high_frequency`;
   - comportamento concentrado em poucos tokens e janela curta;
   - incluída porque queremos verificar se o comportamento bursty persiste fora do recorte histórico.

`DKgv` fica fora desta primeira coorte porque adicionaria carga sem informação proporcional.

## Polling do watcher

Usar 30 segundos por 6 horas.

Racional:

- 60s é grosseiro para candidatos com primeira saída histórica em ~1–5 minutos;
- 30s permite medir empiricamente cobertura <=30s/<=60s;
- três wallets mantêm carga RPC pequena;
- 10s continua prematuro antes de validação operacional de 30s.

O primeiro sync é bootstrap e não conta como confirmação forward. Só transações novas depois da linha de base recebem `observed_at`.

## Modo A — sem Jupiter

Se ainda não houver `JUPITER_API_KEY`, manter o experimento original:

```powershell
python wallet_forward_experiment.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt `
  --hours 6 `
  --interval-seconds 30
```

Esse modo mede somente observabilidade das wallets.

## Modo B — forward + route quotes causais

Com `JUPITER_API_KEY` configurado no `.env`:

```powershell
python wallet_forward_experiment.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt `
  --hours 6 `
  --interval-seconds 30 `
  --with-jupiter-quotes
```

O orquestrador inicia primeiro `wallet_quote_watch.py`, congela o ID-base local e só então inicia o RPC watcher. Assim ações já existentes não geram snapshots de quote retrospectivos.

Para cada **nova compra forward** da coorte, o Quote Watch agenda snapshots em:

```text
+0s, +15s, +30s, +60s, +120s
```

O notional padrão é `COPY_SIZE_USD`, cotado como USDC -> token. A direção é explicitamente `buy`; uma rota sell nunca pode preencher um replay buy.

### Quote-only x transação candidata

Sem `--taker`, Jupiter retorna preço/rota sem transação montada. O snapshot é persistido com `executable=false` e serve apenas como proxy causal de route pricing.

Opcionalmente, pode-se passar uma **chave pública** em `--taker`. Isso permite ao `/order` tentar montar uma transação candidata, mas o projeto:

- não lê chave privada;
- não assina;
- não chama `/execute`;
- não envia transação.

`transaction != null/""` é armazenado como `executable=true` no sentido estrito de "transação candidata montada pelo provider". Isso **não prova landing ou fill real**.

## Rate limit

A implementação espaça requests em pelo menos 1,1s por padrão, de forma conservadora para o tier Free atual do Jupiter (1 request/s, 60/min no bucket principal). Se várias ações ocorrerem em rajada, o atraso real em relação ao target é persistido e aparece na avaliação — não é escondido.

Cada tentativa é auditada em `causal_quote_attempts`, inclusive falhas. Assim o relatório não calcula cobertura apenas sobre quotes que deram certo.

## Avaliação depois do run

Observabilidade da wallet:

```powershell
python evaluate_wallet_forward.py
```

Cobertura/timing dos route quotes:

```powershell
python evaluate_wallet_quotes.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt
```

Replay causal:

```powershell
python wallet_causal_replay.py
```

Sem taker, o replay padrão corretamente rejeita quote-only. Para diagnóstico de timing/price proxy apenas:

```powershell
python wallet_causal_replay.py --allow-proxy-quotes
```

## O que cada saída responde

`evaluate_wallet_forward.py`:

- quantas ações foram realmente observadas;
- chain -> detection lag p50/p95;
- cobertura <=15/30/60/120s;
- comportamento por wallet.

`evaluate_wallet_quotes.py`:

- tentativas totais, sucessos e falhas;
- cobertura em cada delay;
- quote-only x transação candidata;
- atraso real do request em relação ao target;
- atraso de conclusão;
- classes de erro.

`wallet_causal_replay.py`:

- se, depois do atraso real de detecção e do delay declarado, existia quote elegível;
- quanto tempo adicional foi necessário até o quote;
- não mede edge completo enquanto não houver regra de estratégia/saída causal completa.

## Critério para próximo passo

O run não valida edge. Ele decide se observabilidade e route pricing estão bons o suficiente para avançar.

Se 30s for operacionalmente estável e houver route quotes com boa cobertura:

1. aumentar forward somente onde a informação marginal justificar;
2. cruzar com regras congeladas dos arquétipos;
3. calcular replay de entrada/saída com fees/slippage/missingness;
4. promover apenas candidato robusto para Shadow Execution.

Se houver lag alto, muitas falhas RPC/Jupiter ou route coverage ruim, corrigir a camada causal antes de qualquer tentativa ultra-short.

## Guardrails

- Não chamar a wallet mais rápida de melhor.
- Não inferir lucro a partir de frequência ou fingerprint.
- Não misturar bootstrap histórico com observações forward.
- Não tratar quote-only como execução.
- Não tratar transação montada como transação confirmada.
- Não integrar as wallets à estratégia do bot nesta etapa.
- Não alterar filtros da `wave_v3` por causa deste experimento.
