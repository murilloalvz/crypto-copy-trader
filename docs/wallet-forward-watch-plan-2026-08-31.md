# Wallet Forward Watch — Plan 2026-08-31

## Status

RESEARCH / READ ONLY. Este plano não altera `wave_v3_volume_integrity`, não executa ordens e não usa a Solana Tracker Data API.

## Motivo

O deep scan cross-wallet produziu fingerprints descritivos úteis, mas ainda só uma wallet (`7mPti`) passou a gate de cobertura `evidence_ready`. Nenhuma assinatura apareceu em duas wallets com cobertura mínima.

Continuar aumentando backfill indiscriminadamente tem retorno informacional menor do que começar a observar algumas wallets em tempo real e medir o atraso real `chain_time -> observed_at`.

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
   - comportamento muito concentrado em poucos tokens e janela curta, portanto ainda não `evidence_ready`;
   - incluída no forward watch porque o objetivo é verificar se o padrão bursty continua aparecendo fora do recorte histórico.

`DKgv` fica fora desta primeira coorte porque tem apenas três tokens observados, baixa cobertura de sequência e sizing insuficiente; hoje adicionaria carga sem informação proporcional.

## Primeiro run recomendado

Usar polling de 30 segundos por 6 horas:

```powershell
python wallet_watch_forward.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt `
  --hours 6 `
  --interval-seconds 30
```

Racional:

- 60s é aceitável para a 7mPti, mas grosseiro para candidatos com primeira saída histórica em ~1–5 minutos;
- 30s permite medir empiricamente cobertura em <=30s/<=60s sem tentar prometer precisão de 15s;
- com três wallets, a carga permanece muito menor do que um watch amplo;
- 10s ainda não é necessário antes de sabermos se os RPCs públicos sustentam 30s de maneira estável.

O primeiro sync é bootstrap e não conta como confirmação forward. Só transações novas depois da linha de base recebem `observed_at`.

## Avaliação depois do run

```powershell
python evaluate_wallet_forward.py
```

Interpretar:

- quantidade de ações forward por wallet;
- buys/sells e diversidade de tokens;
- lag mínimo, p50, p95 e máximo;
- cobertura <=15s, <=30s, <=60s e <=120s;
- falhas de RPC/sync durante a execução.

## Critério para próximo passo

Este run não valida edge. Ele só decide se a camada de observabilidade é adequada para pesquisa causal.

Se o polling de 30s for operacionalmente estável e produzir ações:

1. manter coleta forward por mais tempo;
2. cruzar entradas observadas com preço executável/liquidez quando essa camada estiver disponível;
3. medir se o comportamento de cada arquétipo persiste fora do backfill;
4. somente depois formular braços de replay/shadow.

Se houver muitas falhas RPC ou lag >60–120s, corrigir observabilidade antes de qualquer tentativa de copiar estratégia ultra-short.

## Guardrails

- Não chamar a wallet mais rápida de melhor.
- Não inferir lucro a partir de frequência ou fingerprint.
- Não misturar bootstrap histórico com observações forward.
- Não integrar as wallets à estratégia do bot nesta etapa.
- Não alterar filtros da `wave_v3` por causa deste experimento.
