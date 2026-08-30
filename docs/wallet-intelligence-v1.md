# Wallet Intelligence v1

Status: **IMPLEMENTADO PARA PESQUISA / READ ONLY**

## Objetivo

Transformar a busca por "big wallets" em pesquisa reproduzível de comportamento. O módulo não copia uma wallet automaticamente e não altera `wave_v3_volume_integrity`.

A pergunta principal deixa de ser apenas "qual wallet ganhou mais?" e passa a ser:

> quais padrões observáveis continuam interessantes depois de medir concentração de lucro, holding, liquidez, frequência e limitações de cópia?

## Fontes usadas

### Solana Tracker PnL V2

Já existente no projeto:

- histórico diário da wallet;
- posições recentes por token;
- PnL realizado;
- ROI;
- quantidade de trades;
- holding time;
- compra média;
- liquidez e market cap atuais;
- filtros de arbitragem e PnL estrito usados pelo discovery.

### Sequência on-chain local

Quando a wallet já foi sincronizada pelo RPC, `Wallet Intelligence` também usa os swaps persistidos em `transactions`:

- timestamps;
- buy/sell por delta do token;
- DEX detectada;
- repetição de ações por token;
- presença de buy + sell;
- intervalo entre swaps.

A sequência local pode ser parcial. O relatório deixa isso explícito.

## O que v1 mede

- tamanho da amostra;
- PnL e ROI medianos;
- win rate por posição com resultado;
- profit factor;
- melhor e pior posição;
- concentração do lucro no maior vencedor e no Top 3;
- PnL sem o maior vencedor;
- holding mediano e P25/P75;
- proxy de escala/reentrada por número de ações por token;
- liquidez e market cap atuais;
- participação de microcaps/small caps na amostra;
- consistência diária e drawdown realizado diário;
- buy/sell, roundtrips, multi-ações e DEX mix quando há sequência local;
- gates para decidir se vale a pena gastar recursos em pesquisa explícita de atraso.

## Arquétipos temporais

São descritivos, não preditivos:

- `ultra_short`: holding mediano abaixo de 5 min;
- `short_term_scalper`: 5–30 min;
- `intraday`: 30 min–6 h;
- `swing`: 6 h–3 dias;
- `position`: acima de 3 dias;
- `unknown`: sem dados de holding.

O nome do arquétipo não afirma que a wallet usa momentum, informação privilegiada ou qualquer intenção que os dados não provem.

## Alertas de robustez

O relatório marca, entre outros:

- amostra pequena;
- lucro concentrado no maior vencedor;
- PnL positivo que desaparece sem o maior vencedor;
- PnL total positivo com ROI mediano não positivo;
- holding curto demais para cópia atrasada;
- cobertura de liquidez baixa;
- pouco capital em tokens atualmente líquidos;
- sequência on-chain ainda pequena.

Esses alertas não "reprovam" a qualidade da wallet. Eles dizem se ela é um bom alvo para pesquisa de **copyability**.

## CLIs

### Uma wallet específica

```powershell
python wallet_intelligence.py <ENDERECO>
```

Para sincronizar primeiro uma página recente do RPC e enriquecer o comportamento on-chain:

```powershell
python wallet_intelligence.py <ENDERECO> --sync-onchain
```

### Shortlist automática de big wallets

```powershell
python research_wallets.py `
  --wallets 250 `
  --top 10 `
  --copyability-limit 25 `
  --liquid-seeds 25 `
  --positions 100
```

Essa execução mantém os filtros atuais de discovery e não relaxa gates para produzir candidatas.

## Limitação central antes da fase de atraso

A API de posições fornece liquidez/market cap atuais, não o estado histórico exato no momento da entrada.

Além disso, candles de 1 minuto não distinguem de forma confiável cópia com 15s e 30s de atraso. Por isso a próxima fase não deve fingir precisão inexistente.

## Próxima fase pré-registrada

1. Rodar a shortlist.
2. Escolher poucas wallets para deep dive com base em robustez + copyability, não só PnL.
3. Sincronizar a sequência on-chain dessas wallets.
4. Medir entradas fracionadas, saídas, reentradas, DEX e timing real.
5. Construir coleta de mercado/quote com resolução suficiente.
6. Testar atraso de cópia em shadow, primeiro sem alterar a `wave_v3`.
7. Só depois avaliar Wallet Intelligence como confirmação/ranking da estratégia.

A `wave_v3` continua baseline e deve seguir coletando em paralelo.
