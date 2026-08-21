# Solana CopyTrader

MVP local para monitorar wallets públicas na Solana, guardar transações em SQLite,
identificar swaps por variação de saldos, calcular um score inicial e criar sinais de
paper trading. **A aplicação não possui chave privada e não envia ordens reais.**

## O que já funciona

- cadastro e remoção lógica de wallets públicas;
- sincronização via JSON-RPC da Solana;
- persistência idempotente em SQLite;
- detecção inicial de swap, transferência de SOL e transferência de token;
- métricas de atividade e Wallet Score preliminar;
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

## Configuração

Edite `.env`. O RPC público funciona para testes, mas pode limitar requisições. Para uso
contínuo, troque `SOLANA_RPC_URL` por um endpoint próprio. Nunca coloque seed phrase ou
chave privada neste projeto.

## Como calcular a performance

1. Sincronize a wallet.
2. Use `Importar histórico anterior` algumas vezes para obter compras e vendas.
3. Clique em `Simular novas cópias`.
4. Na aba `Paper trading`, clique em `Buscar preços e calcular performance`.

Os candles são consultados por minuto no pool de maior liquidez encontrado e ficam em
cache no SQLite. A API pública do GeckoTerminal possui limite de requisições, então a
primeira precificação pode levar alguns segundos.

## Limites honestos desta versão

- O parser usa diferenças de saldo e seleciona o token com maior variação. Transações
  complexas com vários tokens exigirão um parser específico de DEX/agregador.
- O Wallet Score inicial ainda mede principalmente comportamento; as métricas financeiras
  do paper trading aparecem separadamente.
- Os preços usam o fechamento do candle de um minuto e o pool de maior liquidez disponível.
- O P&L atual é realizado e usa FIFO. Posições ainda abertas não são marcadas a mercado.
- Vendas sem uma compra anterior importada são ignoradas, pois o simulador não vende ativos
  que a carteira de paper trading não possui.

## Próximo marco recomendado

Identificar swaps por instruções de Jupiter/Raydium/Orca, marcar posições abertas a mercado
e incorporar performance e risco ao Wallet Score.

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
