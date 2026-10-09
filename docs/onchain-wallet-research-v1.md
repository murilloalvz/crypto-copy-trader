# On-chain Wallet Research v1

Status: IMPLEMENTADO / AGUARDA VALIDAÇÃO LOCAL.

Objetivo: manter a pesquisa de comportamento de big wallets avançando quando os créditos da Solana Tracker Data API estiverem indisponíveis.

## O que esta etapa faz

`wallet_onchain_research.py` usa somente:

- Solana RPC público/configurado;
- parser de swaps já existente no projeto;
- SQLite local.

Ela não chama a Solana Tracker Data API e não altera `wave_v3_volume_integrity`.

Para cada wallet, o script pode sincronizar múltiplas páginas de assinaturas e descrever a sequência de swaps observada:

- quantidade de swaps/tokens;
- compras e vendas;
- mix de DEX;
- percentual de tokens com buy+sell observado;
- tokens com múltiplas ações;
- indício de scale-in (duas ou mais compras antes da primeira venda observada);
- indício de saída parcial (duas ou mais vendas depois da primeira compra observada);
- indício de reentrada (nova compra depois da primeira venda observada);
- tempo da primeira compra até a primeira venda observada;
- span da primeira compra até a última venda observada;
- gap mediano entre swaps.

## Limites metodológicos

A amostra RPC pode ser parcial. Ausência de venda não prova que a wallet nunca vendeu; a venda pode estar fora da janela sincronizada.

Esta etapa não afirma:

- PnL/ROI da wallet;
- liquidez ou market cap no momento da entrada;
- slippage/impacto executável;
- causalidade ou edge;
- estratégia completa quando a janela on-chain é incompleta.

Os nomes `scale-in`, `partial exit` e `reentry` significam somente padrões observados na sequência local sincronizada.

## Primeiro alvo

A primeira candidata de pesquisa já encontrada antes do esgotamento de créditos foi:

`7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`

Ela permanece apenas como alvo de pesquisa; não é aprovação para copy trading.

Comando inicial conservador:

```powershell
python wallet_onchain_research.py 7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH --pages 3
```

Com `MAX_SIGNATURES_PER_SYNC=30`, três páginas cobrem até aproximadamente 90 assinaturas antes de deduplicação/falhas. Aumentar páginas só depois de observar estabilidade/rate-limit do RPC.

## Próxima decisão

Depois da primeira execução, revisar:

1. quantos swaps reais foram reconhecidos;
2. cobertura temporal da amostra;
3. percentual de roundtrips observados;
4. padrão de scale-in/partial-exit/reentrada;
5. DEX mix;
6. necessidade de backfill adicional.

Quando a Data API renovar, combinar este comportamento on-chain com PnL, posições e liquidez, sem misturar ausência de dados com evidência negativa.
