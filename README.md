# Solana CopyTrader

MVP local para monitorar wallets públicas na Solana, guardar transações em SQLite,
confirmar swaps on-chain, calcular performance e criar sinais de paper trading.
**A aplicação não possui chave privada e não envia ordens reais.**

## O que já funciona

- cadastro e remoção lógica de wallets públicas;
- sincronização via JSON-RPC da Solana;
- persistência idempotente em SQLite;
- confirmação de swaps por program ID e fluxo de saldos;
- suporte inicial a Jupiter v4-v6, Raydium AMM/CPMM/CLMM e Pump.fun/PumpSwap;
- separação entre swaps, atividade em DEX e transferências comuns;
- Wallet Score financeiro apenas quando existe amostra mínima;
- paper trades com tamanho, slippage e atraso configuráveis;
- preços históricos por minuto via GeckoTerminal, com cache local;
- reconstrução de posições FIFO e P&L realizado;
- win rate, retorno e drawdown realizado;
- importação paginada de lotes anteriores do histórico;
- dashboard Streamlit.

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

Adicionar Orca e outros protocolos, marcar posições abertas a mercado e criar uma rotina
para pesquisar e validar wallets de traders em vez de carteiras de corretoras.

## Estrutura

```text
app.py                 dashboard
src/solana.py          cliente RPC e parser
src/database.py        schema e acesso SQLite
src/services.py        sincronização e paper trading
src/analytics.py       métricas e score
src/prices.py          preços históricos e cache
tests/test_parser.py   teste do parser
```

Dados de mercado on-chain: GeckoTerminal. Powered by CoinGecko.
