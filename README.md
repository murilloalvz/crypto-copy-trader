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
- filtro de liquidez atual ponderado pelo capital da wallet;
- Copyability Score separado, com liquidez, ritmo, posição média e proxy de impacto.
- watchlist em três níveis: aprovada, observação e reprovada;
- detector inicial de convergência entre compras de wallets independentes.

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
SOLANA_TRACKER_TIMEOUT_SECONDS=12
SOLANA_TRACKER_MAX_ATTEMPTS=3
```

Não envie essa chave para o GitHub nem para outra pessoa. O `.env.example` contém apenas
o nome da variável. Timeout e tentativas limitam quanto uma consulta instável pode
segurar a rodada; falhas no histórico de uma wallet são registradas e as demais continuam.
O terminal mostra `[source] 1/5` até `[source] 5/5` enquanto combina os cinco
leaderboards, antes das etapas `liquid-seed`, `history` e `liquidity`.
Para um teste menor e mais rápido:

```powershell
python discover.py --wallets 50 --top 10
```

O funil é independente do dashboard:

```text
discover.py -> fonte -> filtros -> Candidate Score -> liquidez -> Copyability Score -> watchlist
app.py      -> monitoramento manual da wallet escolhida
```

O Solana Tracker foi escolhido porque entrega endereço público real, janelas recentes,
PnL/ROI, trades, tokens, dias positivos/negativos, último trade e histórico diário. A
requisição ativa `excludeArbitrage=true`, `pnlMode=strict`,
`maxSingleTokenPct=30`, no mínimo 50 trades, 10 dias ativos e US$ 500 investidos.
O lote combina leaderboards ordenados por PnL, ROI, win rate, dias ativos e também por
menor quantidade de trades permitida, removendo duplicatas. Isso reduz o viés do topo
dominado por bots sem relaxar os filtros locais. Além disso, 25 endereços da amostra são
obtidos, por padrão, a partir da [busca de tokens](https://docs.solanatracker.io/data-api/search/token-search)
com pelo menos US$ 250 mil de liquidez e US$ 100 mil de volume em 24 horas. O endpoint
oficial de [traders do token](https://docs.solanatracker.io/data-api/pnl-v2/token/get-token-traders)
fornece as wallets públicas; carteiras marcadas como desenvolvedor são descartadas. Essas
wallets não ganham pontos por essa origem: histórico, filtros, Candidate Score e
Copyability Score continuam iguais. Para reduzir o viés de selecionar apenas grandes
vencedores, cada mercado intercala traders por PnL realizado, ROI, último trade e menor
capital investido. Posições já encerradas também participam da descoberta; o funil de 30
dias elimina depois amostras fracas, inativas ou excessivamente rápidas. Birdeye ficou
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
token representa mais de 30% do PnL. Como a classificação de arbitragem da fonte não é
infalível, o filtro local também elimina capital investido inferior a US$ 500 e posição
média observada abaixo de 60 segundos. Hold time ausente continua como desconhecido, não
como zero.

Não entram no Candidate Score: liquidez por token, slippage real da wallet e distribuição
por trade. A separação é intencional: qualidade financeira e viabilidade de execução são
problemas diferentes. O drawdown atual é
calculado sobre o PnL realizado diário e dividido pelo capital investido no período; ele não
é um drawdown patrimonial completo. As janelas 7/30/90 dias são sobrepostas e representam
consistência em horizontes diferentes, não três períodos independentes.

### Filtro de liquidez e Copyability Score

Somente as melhores candidatas do primeiro funil são enriquecidas pelo endpoint read-only
de [posições da wallet](https://docs.solanatracker.io/data-api/pnl-v2/wallet/get-wallet-positions).
Por padrão são consultadas até 50 posições recentes, com atividade em 30 dias e PnL
`strict`. O endpoint informa a liquidez atual do mercado principal de cada token. Nada é
gravado no banco do tracker.

As barreiras conservadoras desta versão são:

- pelo menos 5 posições na amostra;
- liquidez conhecida em pelo menos 60% dos tokens amostrados;
- pelo menos 50% dos tokens conhecidos com US$ 50 mil ou mais de liquidez;
- pelo menos 60% do capital amostrado nesses tokens líquidos;
- posição média de pelo menos 5 minutos;
- no máximo 20 trades por dia em 30 dias;
- Copyability Score mínimo de 60/100.

O Copyability Score de 0 a 100 não usa PnL, ROI ou win rate:

- 30 pontos: parcela do capital amostrado em tokens com ao menos US$ 50 mil de liquidez;
- 15 pontos: liquidez mediana atual, normalizada em escala logarítmica entre US$ 10 mil e
  US$ 500 mil;
- 15 pontos: proxy de impacto, usando compra média da wallet / liquidez atual do token;
- 20 pontos: tempo médio de posição, com pontuação máxima a partir de 30 minutos;
- 15 pontos: frequência, com pontuação máxima até 5 trades por dia e queda progressiva;
- 5 pontos: cobertura dos dados de liquidez na amostra.

A ponderação por capital evita que uma wallet passe apenas por negociar muitos tokens
líquidos com valores pequenos enquanto concentra o dinheiro em tokens rasos. Liquidez zero
é tratada como ilíquida; campo ausente é tratado como desconhecido e reduz a cobertura.
Uma wallet pode ter Candidate Score alto e ser reprovada para cópia.

### Watchlist e convergência de wallets

O resultado deixou de ser apenas binário, sem reduzir as barreiras de segurança:

- `APROVADA`: passou por todas as barreiras e pode avançar ao laboratório de paper copy;
- `OBSERVAÇÃO`: tem Candidate Score mínimo de 75 e Copyability Score mínimo de 55,
  mas falhou somente por participação de tokens ou capital líquido. Pode contribuir com
  sinais coletivos, porém nunca autoriza cópia individual;
- `REPROVADA`: possui dados insuficientes, estratégia rápida/HFT, baixa qualidade ou outra
  barreira operacional e não participa da watchlist.

O módulo puro `src/waves.py` é a primeira fundação do futuro Wave Detector. Ele normaliza
compras públicas e procura convergência no mesmo token dentro de cinco minutos. Uma única
wallet nunca cria um candidato. Por padrão, uma wallet aprovada pesa 1,0 e uma wallet em
observação pesa 0,5; são exigidas ao menos duas wallets independentes e peso total de 1,5.
Eventos repetidos da mesma wallet, vendas, wallets reprovadas e sinais fora da janela são
ignorados.

O resultado ainda se chama `WaveCandidate`, não `Wave Score`: convergência sozinha não
autoriza nem mesmo uma entrada fictícia. Antes do paper trading, a próxima etapa deverá
consultar liquidez e impacto no momento do sinal, concentração de holders, autoridades de
mint/freeze, idade do token e aceleração de preço/volume. O módulo atual não monitora a
rede em tempo real e não executa transações.

Use `--copyability-limit` para controlar quantas candidatas do primeiro funil recebem a
consulta adicional. O padrão é 25:

```powershell
python discover.py --wallets 250 --top 10 --copyability-limit 25
```

Use `--liquid-seeds` para controlar quantas das wallets analisadas partem desses mercados.
O valor deve ser menor ou igual a `--wallets` e o máximo é 200:

```powershell
python discover.py --wallets 250 --top 10 --copyability-limit 25 --liquid-seeds 50
```

Limitações honestas: a liquidez é atual, não histórica; a compra média/liquidez é um proxy,
não uma simulação de rota; volume 24h, profundidade por faixa de preço, slippage histórico e
latência real ainda não entram no score.

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

Antes de consultar o candle, cada sinal passa por uma barreira individual de mercado. O
padrão exige ao menos US$ 50 mil de liquidez e US$ 10 mil de volume em 24 horas no pool
selecionado. Um sinal reprovado continua registrado para auditoria como
`skipped_illiquid` ou `skipped_low_volume`, com a explicação em `price_error`, mas não
entra no P&L. Os limites podem ser alterados no `.env` sem mudar o código:

```text
MIN_SIGNAL_LIQUIDITY_USD=50000
MIN_SIGNAL_VOLUME_24H_USD=10000
MAX_PRICE_RETRY_ATTEMPTS=3
```

Falhas de preço são classificadas para evitar consultas inúteis:

- `price_retryable`: rede, limite temporário ou indisponibilidade;
- `price_retry_exhausted`: atingiu o máximo configurado de tentativas;
- `price_no_pool`: nenhum pool disponível para o token;
- `price_no_historical_candle`: o pool não possui candle para aquele minuto;
- `price_distant_historical_candle`: o candle está distante demais do sinal;
- `price_permanent_error`: outra resposta definitiva que não deve ser repetida.

O provedor faz backoff exponencial para erros temporários, incluindo HTTP 429. Falhas
permanentes e sinais já bloqueados por mercado não são consultados novamente a cada clique.
O dashboard mostra a cobertura total (`swaps precificados / swaps confirmados`) e a
cobertura entre sinais não bloqueados. P&L, retorno, win rate e drawdown usam somente
compras e vendas elegíveis e precificadas; essa limitação fica explícita na interface.

Os candles são consultados por minuto no pool ativo selecionado por volume e liquidez e
ficam em cache no SQLite. A API pública do GeckoTerminal possui limite de requisições,
então a primeira precificação pode levar alguns segundos.

Ao abrir uma versão nova do app, as transações já armazenadas são reprocessadas. Paper
trades originados de falsos positivos antigos são marcados como ignorados, sem apagar o
histórico bruto da blockchain.

## Limites honestos desta versão

- O parser exige duas evidências: um programa de DEX suportado precisa ter sido invocado e
  o fluxo de saldos precisa ter formato de troca. Rotas muito complexas podem ser ignoradas
  de forma conservadora em vez de virarem falsos swaps.
- O Wallet Score fica como `Dados insuficientes` até existirem pelo menos 5 trades fechados.
  Depois considera retorno, win rate, drawdown, tamanho da amostra, atividade e frequência.
- Os preços usam o fechamento do candle de um minuto e o pool priorizado por volume 24h.
- Liquidez e volume são fotografias atuais; a barreira evita sinais claramente rasos, mas
  não substitui uma cotação de rota nem mede a liquidez histórica do instante do trade.
- O P&L atual é realizado e usa FIFO. Posições ainda abertas não são marcadas a mercado.
- Vendas sem uma compra anterior importada são ignoradas, pois o simulador não vende ativos
  que a carteira de paper trading não possui.

## Próximo marco recomendado

Executar paper trading por vários dias nas wallets aprovadas, registrar latência real e
comparar o preço detectado com uma cotação de rota para estimar slippage reproduzível.

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
