# Solana CopyTrader

MVP local para monitorar wallets públicas na Solana, guardar transações em SQLite,
confirmar swaps on-chain, calcular performance e criar sinais de paper trading.
**A aplicação não possui chave privada e não envia ordens reais.**

## O que já funciona

- cadastro e remoção lógica de wallets públicas;
- sincronização via JSON-RPC da Solana;
- persistência idempotente em SQLite;
- confirmação de swaps por program ID e fluxo de saldos;
- suporte inicial a Jupiter v4-v6, Raydium AMM/CPMM/CLMM/LaunchLab/Router,
  Pump.fun/PumpSwap, Orca Whirlpool e Meteora DLMM/DAMM/DBC;
- separação entre swaps, atividade em DEX e transferências comuns;
- diagnóstico dos programas encontrados quando uma wallet fica sem swaps confirmados;
- Wallet Score financeiro apenas quando existe amostra mínima;
- paper trades com tamanho, slippage e atraso configuráveis;
- preços históricos por minuto via GeckoTerminal, com cache local;
- reconstrução de posições FIFO e P&L realizado;
- win rate, retorno e drawdown realizado;
- importação paginada de lotes anteriores do histórico;
- dashboard Streamlit.
- discovery automático de wallets candidatas, separado do tracker;
- filtros contra arbitragem, HFT, inatividade, amostra pequena e one-hit winners;
- Candidate Score explicável com consistência, ROI, drawdown e penalizações básicas.

## Wallet discovery

O comando abaixo consulta apenas dados públicos e não grava transações nem adiciona
automaticamente nenhuma wallet ao tracker:

```powershell
python discover.py
```

A fonte principal é o [Solana Tracker PnL V2](https://docs.solanatracker.io/data-api/pnl-v2/leaderboard/solana-traders-leaderboard).
O plano gratuito informa 10.000 requisições mensais. Crie uma API key no painel do
Solana Tracker e adicione ao `.env`:

```text
SOLANA_TRACKER_API_KEY=cole_sua_chave_aqui
```

Não envie essa chave para o GitHub nem para outra pessoa. O `.env.example` contém apenas
o nome da variável. Para um teste menor e mais rápido:

```powershell
python discover.py --wallets 50 --top 10
```

O funil é independente do dashboard:

```text
discover.py -> fonte -> filtros -> Candidate Score -> wallet candidata
app.py      -> monitoramento manual da wallet escolhida
```

O Solana Tracker foi escolhido porque entrega endereço público real, janelas recentes,
PnL/ROI, trades, tokens, dias positivos/negativos, último trade e histórico diário. A
requisição ativa `excludeArbitrage=true`, `pnlMode=strict` e
`maxSingleTokenPct=50`. O lote combina leaderboards ordenados por PnL, ROI e win rate,
removendo duplicatas, para não nascer dominado apenas por PnL nominal. Birdeye ficou
preparado como fallback técnico. Dune permite
consultas personalizadas, mas exige manter SQL e execução; DexScreener é excelente para
tokens/pools, mas sua API pública não oferece um leaderboard geral de wallets.

### Fórmula do Candidate Score

O score de 0 a 100 serve somente para ordenar candidatas:

- 25 pontos: consistência em 7/30/90 dias e proporção de dias positivos;
- 15 pontos: ROI 30d com escala logarítmica e teto em 100%;
- 15 pontos: drawdown realizado relativo ao valor investido;
- 15 pontos: tamanho da amostra, favorecendo 50 a 300 trades;
- 10 pontos: win rate, sem tratá-lo isoladamente;
- 10 pontos: recência do último trade;
- 5 pontos: diversidade de tokens;
- 5 pontos: percentil de PnL dentro do lote, limitando o peso do valor nominal.

Depois são descontadas penalizações por frequência difícil de copiar, concentração do
lucro em um único dia, poucos resultados realizados e tempo médio de posição muito curto.
O filtro da fonte também exclui wallets marcadas como arbitragem e aquelas em que um único
token representa mais de 50% do PnL.

Ainda não entram no score: liquidez por token, slippage real da wallet e distribuição por
trade. A fonte não fornece esses três itens diretamente no leaderboard. O drawdown atual é
calculado sobre o PnL realizado diário e dividido pelo capital investido no período; ele não
é um drawdown patrimonial completo.

## Modo demonstração offline

Se a rede bloquear os RPCs da Solana, ative `Modo demonstração offline` na barra
lateral. O app cria automaticamente uma wallet de demonstração e não faz nenhuma
requisição externa.

1. Clique em `Carregar dados offline` para importar 10 transações sintéticas.
2. Clique em `Simular novas cópias` para criar os paper trades.
3. Abra `Paper trading` e clique em `Aplicar preços sintéticos e calcular`.

Esse fluxo passa pelo mesmo parser, banco SQLite, posições FIFO, P&L e Wallet Score do
modo normal. As cinco compras e cinco vendas, os tokens e os preços são inteiramente
sintéticos e aparecem identificados no dashboard. Eles servem para validar o software,
não para avaliar uma wallet ou estratégia real.

## Instalação no Windows

Requer Python 3.11 ou 3.12.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

Abra o endereço exibido no terminal, normalmente `http://localhost:8501`.

Para executar os testes locais:

```powershell
python -m unittest discover -s tests -v
```

## Configuração

Edite `.env`. O endpoint público atual é `https://api.mainnet.solana.com`; a aplicação
migra automaticamente a configuração antiga `api.mainnet-beta.solana.com`. O RPC público
funciona para testes, mas pode limitar requisições. Em falhas de rede ou TLS, o cliente
tenta automaticamente o endpoint público alternativo definido em
`SOLANA_RPC_FALLBACK_URLS`. Para uso contínuo, troque `SOLANA_RPC_URL` por um endpoint
próprio. Nunca coloque seed phrase ou chave privada neste projeto.

## Como calcular a performance

1. Sincronize a wallet.
2. Use `Importar histórico anterior` algumas vezes para obter compras e vendas.
3. Clique em `Simular novas cópias`.
4. Na aba `Paper trading`, clique em `Buscar preços e calcular performance`.

Os candles são consultados por minuto no pool de maior liquidez encontrado e ficam em
cache no SQLite. A API pública do GeckoTerminal possui limite de requisições, então a
primeira precificação pode levar alguns segundos.

Ao abrir uma versão nova do app, as transações já armazenadas são reprocessadas. Paper
trades originados de falsos positivos antigos são marcados como ignorados, sem apagar o
histórico bruto da blockchain.

## Limites honestos desta versão

- O parser exige duas evidências: um programa de DEX suportado precisa ter sido invocado e
  o fluxo de saldos precisa ter formato de troca. Rotas muito complexas podem ser ignoradas
  de forma conservadora em vez de virarem falsos swaps.
- O Wallet Score fica como `Dados insuficientes` até existirem pelo menos 5 trades fechados.
  Depois considera retorno, win rate, drawdown, tamanho da amostra, atividade e frequência.
- Os preços usam o fechamento do candle de um minuto e o pool de maior liquidez disponível.
- O P&L atual é realizado e usa FIFO. Posições ainda abertas não são marcadas a mercado.
- Vendas sem uma compra anterior importada são ignoradas, pois o simulador não vende ativos
  que a carteira de paper trading não possui.

## Próximo marco recomendado

Validar a liquidez dos tokens operados pelas candidatas e criar um Copyability Score
separado. Isso não deve ser confundido com o Candidate Score deste primeiro funil.

## Estrutura

```text
app.py                 dashboard
discover.py            CLI de discovery, filtros e Top 10
src/demo.py            transações e preços sintéticos do modo offline
src/discovery/          fontes, métricas, filtros e ranking de candidatas
src/solana.py          cliente RPC e parser
src/database.py        schema e acesso SQLite
src/services.py        sincronização e paper trading
src/analytics.py       métricas e score
src/prices.py          preços históricos e cache
tests/test_parser.py   teste do parser
```

Dados de mercado on-chain: GeckoTerminal. Powered by CoinGecko.
