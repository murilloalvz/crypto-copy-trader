# Runtime v3 UTF-8 / live-output validation — 2026-08-30

Status: **VALIDADO OPERACIONALMENTE EM JANELA CURTA / PAPER-READ ONLY**

## Execução

- Janela: 19:08:53–19:38:57 BRT (~30 min)
- `Hours=0.5`
- `PriceIntervalMinutes=1`
- `DiscoveryIntervalMinutes=15`
- `Tokens=50`
- `Top=3`
- ExitCode: 0
- Banco auditado: `copytrader(20260830-231357).db`
- `integrity_check = ok`
- `quick_check = ok`
- 0 violações de foreign key

## Objetivo

Validar a correção que força UTF-8 e saída Python sem buffering no launcher, sem alterar `wave_v3_volume_integrity`, o T0 ou as políticas de saída.

## Resultado

- saída do monitor apareceu ao vivo durante toda a janela;
- acentos e caracteres Unicode foram impressos corretamente;
- 2/2 discovery rounds concluíram sem `UnicodeEncodeError`;
- 30 ciclos de liquidação foram executados;
- 2 novos sinais foram persistidos (IDs 125 e 126), ambos com cinco posições de exit engine;
- nenhum HTTP 429 foi observado na janela;
- 60/60 tentativas HTTP retornaram 200 na primeira tentativa;
- runtime das observações: `exit_runtime_v3_adaptive_provider_budget`;
- scheduler manteve cadência de ~60s; a única pequena compressão ocorreu ao redor do segundo discovery, sem cauda recorrente de 120s.

## Observação de provider

O sinal SOL (ID 126) apresentou `distant_historical_candle` repetidamente no GeckoTerminal, enquanto USELESS (ID 125) teve observações válidas. Isso é classificado separadamente do problema de encoding e não reabre a correção do scheduler/launcher.

## Decisão

- correção UTF-8 / live output: **VALIDADA OPERACIONALMENTE**;
- não há motivo para continuar iterando no launcher neste momento;
- manter a coleta forward da v3 congelada como baseline;
- próxima prioridade de desenvolvimento/pesquisa: **Wallet Intelligence**, em trilha paralela, sem alterar a entrada v3 atual.

## Próxima prioridade — Wallet Intelligence

Objetivo: identificar wallets Solana com comportamento realmente copiável, reconstruir estratégias de entrada/saída e medir se o edge sobrevive a atrasos e custos realistas.

Primeiras perguntas de pesquisa:

1. o que as wallets compram e em que estado de mercado entram;
2. quanto tempo seguram e como fracionam compras/vendas;
3. concentração de lucro e dependência de outliers;
4. sinais de insider/dev-connected behavior a excluir;
5. performance simulada com atrasos de 15s, 30s, 60s e 120s;
6. quais arquétipos permanecem copiáveis após slippage/fees;
7. uso posterior como confirmação/shadow feature contra a v3 baseline.
