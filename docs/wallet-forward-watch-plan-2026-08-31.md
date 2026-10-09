# Wallet Forward Watch — Plan 2026-08-31

## Status

RESEARCH / READ ONLY. Este experimento não altera `wave_v3_volume_integrity`, não usa a Solana Tracker Data API, não lê chave privada, não assina e não envia transações.

A integração Jupiter Swap V2 `GET /order` já passou por smoke test real em rede sem proxy: a API key foi aceita, uma rota SOL -> USDC foi retornada pelo router `metis` e nenhuma transação foi montada sem `taker`. A rede da escola apresentou falha TLS por certificado raiz não confiável, portanto não deve ser usada para a coleta longa.

## Pergunta do experimento

O objetivo é medir duas camadas separadas:

1. quão rápido novas ações de wallets públicas são observadas via RPC;
2. depois de uma nova compra ser observada, quão rápido uma rota Jupiter pode ser cotada causalmente.

Isto ainda não mede edge nem lucro. O objetivo é descobrir se a camada de observação/rota é boa o suficiente para justificar replay de estratégia e, mais tarde, shadow execution.

## Coorte forward v1

Arquivo:

```text
wallets/forward-watch-archetypes-2026-08-31.txt
```

Wallets:

- `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`: referência comportamental mais madura; histórico sugere holding mais longo, saída mista e reentrada ocasional.
- `Gf9XgdmvNHt8fUTFsWAccNbKeyDXsgJyZN8iFJKg5Pbd`: candidato ultra-short, single-exit dominante e reentrada rara, mas com cobertura de sequência incompleta.
- `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`: candidato bursty/ultra-short, staged exit/reentry, ainda com poucos tokens e janela histórica curta.

`DKgv` permanece fora da primeira coorte por baixa cobertura e pouco ganho informacional adicional.

## Polling

Baseline planejado: 30 segundos por 6 horas.

- 60s é grosseiro para wallets cuja primeira saída histórica pode ocorrer em poucos minutos;
- 30s permite medir diretamente cobertura <=30s e <=60s;
- três wallets mantêm carga RPC pequena;
- 10s ainda não foi justificado operacionalmente.

O primeiro sync do watcher é apenas bootstrap. Transações já existentes não viram confirmações forward.

## Run manifest

`wallet_forward_experiment.py` agora cria um **run manifest** persistido em `wallet_forward_runs` antes de iniciar os processos.

O manifest congela:

- `run_key` único;
- timestamp inicial/final;
- ID-base de `wallet_forward_observations`;
- ID final da coleta;
- coorte exata;
- polling RPC;
- delays de quote;
- notional de cópia;
- modo de quote (`none`, `proxy` ou `assembled_candidate`);
- status `ACTIVE`, `COMPLETED` ou `ABORTED`.

Esse manifest evita que observações antigas ou de outra execução entrem silenciosamente no checkpoint.

## Modo preferido — forward + Jupiter

Com `JUPITER_API_KEY` configurado no `.env` e internet estável:

```powershell
python wallet_forward_experiment.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt `
  --hours 6 `
  --interval-seconds 30 `
  --with-jupiter-quotes
```

O orquestrador congela um único baseline e passa esse mesmo ID ao Quote Watch. Para cada **nova compra forward** da coorte são agendadas tentativas em:

```text
+0s, +15s, +30s, +60s, +120s
```

O notional padrão é `COPY_SIZE_USD`, cotado como USDC -> token.

Cada tentativa — sucesso ou falha — é persistida em `causal_quote_attempts`. Assim a cobertura não sofre survivorship bias por olhar apenas quotes bem-sucedidos.

## Modo sem Jupiter

Se for necessário coletar apenas observabilidade RPC:

```powershell
python wallet_forward_experiment.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt `
  --hours 6 `
  --interval-seconds 30
```

A run ainda recebe manifest, mas `quote_mode=none`.

## Quote-only x transação candidata

Sem `--taker`, Jupiter retorna preço/rota sem montar transação. O snapshot fica `executable=false` e deve ser tratado como **proxy causal de route pricing**, não como fill.

Com uma chave **pública** em `--taker`, `/order` pode montar uma transação candidata. O projeto continua sem chave privada, sem assinatura e sem `/execute`. Mesmo `executable=true` neste estágio significa apenas "transação candidata montada pelo provider"; não comprova landing, confirmação ou fill real.

## Rate limit e atraso real

O Quote Watch espaça requests em pelo menos 1,1s por padrão. Se várias compras ocorrerem em rajada, o atraso do request e da conclusão em relação ao target é persistido em vez de ser escondido.

## Checkpoint v2 — escopo causal correto

O relatório principal agora é:

```powershell
python wallet_forward_checkpoint.py
```

Sem `--run-key`, ele usa a run `COMPLETED` mais recente. Uma run específica pode ser auditada com:

```powershell
python wallet_forward_checkpoint.py --run-key <RUN_KEY>
```

O checkpoint v2 corrige três riscos metodológicos:

1. **SELL não entra no denominador do replay de entrada.** O coletor automático atual captura rota somente para BUY, então misturar SELL faria a cobertura parecer artificialmente pior.
2. **Quotes são ligados ao evento exato.** Um quote do mesmo token capturado por outra ação/wallet/run não pode preencher o replay de um BUY diferente.
3. **Observações são limitadas pelos IDs do manifest.** Dados anteriores ao baseline ou posteriores ao encerramento não entram na amostra da run.

A seção Wallet Observability continua usando BUY + SELL porque seu objetivo é medir detecção geral. A seção Causal Replay é explicitamente **ENTRY BUY ONLY**.

Sem run manifest, o checkpoint permite apenas leitura legada de latência e bloqueia route quote/replay para não misturar execuções.

## Interpretação do replay

- `strict`: exige quote marcado como transação candidata montada;
- `proxy`: permite quote-only para medir timing/preço de rota.

Em uma run sem `--taker`, `strict=0` é esperado e não deve ser interpretado como falha do proxy.

O replay aplica apenas informação disponível depois de `observed_at + decision_delay`. Nenhum dado do futuro pode satisfazer uma decisão passada.

## Smoke operacional antes das 6h

Depois de atualizar a branch e passar a suíte local, executar primeiro uma run curta para validar coordenação de processos, manifest e encerramento limpo:

```powershell
python wallet_forward_experiment.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt `
  --hours 0.05 `
  --interval-seconds 30 `
  --with-jupiter-quotes
```

`0.05h` equivale a aproximadamente 3 minutos. É um smoke de infraestrutura; pode terminar com zero compras novas porque depende da atividade real das wallets.

Depois:

```powershell
python wallet_forward_checkpoint.py
```

Se a run curta fechar `COMPLETED`, sem erro de RPC/Jupiter/processo/manifest, a coleta de 6h fica operacionalmente liberada. Zero BUY em 3 minutos não invalida o smoke; apenas significa que a parte event-driven de quote ainda não recebeu evento real.

## Rede

- Internet da escola: **não usar** para esta coleta; houve `SEC_E_UNTRUSTED_ROOT`/TLS handshake failure por cadeia de certificado não confiável.
- Hotspot: smoke Jupiter passou.
- Coleta de 6h: preferir internet residencial estável para não confundir falha de rede com latência do sistema.

Não desabilitar verificação TLS e não usar bypass como `curl -k` para contornar o problema da escola.

## Gate para próximo passo

A run não valida edge. Ela só pode liberar a próxima etapa se houver dados suficientes para auditar:

- cobertura de observação das wallets;
- p50/p95 de `chain_time -> observed_at`;
- tentativas Jupiter por delay;
- sucesso/falha e classes de erro;
- request/completion lag;
- missingness;
- cobertura causal proxy por BUY.

Depois disso, a sequência continua:

```text
forward observability
-> causal route replay
-> estratégia congelada + custos/slippage
-> shadow execution
-> execução real controlada somente muito depois
```

## Guardrails

- Não chamar wallet mais rápida de melhor.
- Não inferir lucro a partir de frequência ou fingerprint.
- Não misturar bootstrap histórico com observações forward.
- Não misturar runs diferentes.
- Não usar quote de outro evento para preencher um replay.
- Não tratar quote-only como execução.
- Não tratar transação montada como transação confirmada.
- Não integrar wallets à estratégia do bot nesta etapa.
- Não alterar filtros da `wave_v3` por causa deste experimento.
