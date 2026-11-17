# Forward Wallet Watch v1

## Status

IMPLEMENTADO como infraestrutura de pesquisa em `wallet_watch_forward.py`, `src/wallet_forward_collector.py` e `src/wallet_forward_observations.py`.

Modo: **RESEARCH / READ ONLY**. Usa Solana RPC, não usa Solana Tracker Data API e não cria ordens.

## Por que existe

O backfill RPC mostra quando uma transação entrou na blockchain (`block_time`), mas não mostra quando **nosso sistema** teria tomado conhecimento dela em tempo real.

Para testar a tese "wallet boa entrou → nós conseguimos confirmar cedo o suficiente → o edge sobrevive ao atraso", precisamos persistir dois tempos:

- `chain_time`: tempo da transação na Solana;
- `observed_at`: tempo em que o nosso coletor viu a ação.

Sem `observed_at`, um replay pode cometer look-ahead e fingir que uma transação sincronizada horas depois estava disponível imediatamente.

## Bootstrap causal

O watcher faz um sync inicial por wallet e trata esse estado como linha de base.

**As transações descobertas no bootstrap não viram confirmações forward.**

Depois da linha de base, somente assinaturas novas que aparecem em ciclos posteriores recebem `observed_at` e são persistidas em `wallet_forward_observations`.

Isso evita marcar um histórico antigo como se fosse uma entrada nova da wallet.

## Uso

Uma wallet:

```powershell
python wallet_watch_forward.py 7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH --hours 2
```

Várias wallets via arquivo:

```powershell
python wallet_watch_forward.py --file wallets.txt --hours 6 --interval-seconds 60
```

O limite padrão de segurança é 20 wallets. O polling mínimo permitido é 10 segundos; isso não significa que 10 segundos seja recomendado para grandes coortes.

## O que é persistido

Apenas swaps novos, bem formados e suportados:

- wallet;
- token mint;
- buy/sell derivado do delta de token;
- `chain_time`;
- `observed_at`;
- signature;
- DEX;
- source.

O `observation_key` impede duplicar a mesma ação quando o RPC devolve novamente a assinatura.

## Integração com Opportunity Intelligence

`load_wallet_forward_observations()` converte os registros persistidos em `WalletActionObservation`.

`OpportunityContextSnapshot` só usa observações com `observed_at <= as_of`.

Essa camada ainda não define:

- quantos segundos de atraso são aceitáveis;
- quantas wallets precisam confirmar;
- qual wallet tem peso maior;
- se buy de wallet implica buy do bot;
- janela ótima de confirmação;
- estratégia/exit selecionada.

Essas regras precisam nascer de replay causal e validação forward, não de escolha manual olhando os vencedores.

## Limitações conhecidas

1. O watcher depende da cobertura e latência dos RPCs configurados.
2. `MAX_SIGNATURES_PER_SYNC` limita quantas assinaturas recentes o `sync_wallet` enxerga por ciclo; wallets extremamente rápidas podem exigir outro desenho.
3. O relógio local precisa estar razoavelmente sincronizado; `observed_at < chain_time` é rejeitado em vez de ser corrigido silenciosamente.
4. O parser atual só registra swaps reconhecidos pela infraestrutura existente.
5. A tabela histórica `transactions` usa `signature` como chave primária global. Uma mesma transação relevante para duas wallets acompanhadas pode exigir revisão de modelagem antes de uma coorte multi-wallet muito grande.
6. Polling não equivale a stream; a latência medida inclui o intervalo de polling, RPC e processamento.

## Próximo experimento útil

Quando houver uma coorte de wallets realmente selecionada para pesquisa, rodar o watcher forward em paralelo com Wave e, futuramente, Social/X. Para cada ação de wallet, medir:

- lag `observed_at - chain_time`;
- retorno após observação em horizontes pré-fixados;
- preço executável após 15s/30s/60s/120s quando existir quote layer adequada;
- liquidez/slippage;
- se múltiplas wallets independentes melhoram o sinal;
- se confirmação wallet acrescenta algo ao Wave sozinho.
