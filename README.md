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

## Limites honestos desta versão

- O parser usa diferenças de saldo e seleciona o token com maior variação. Transações
  complexas com vários tokens exigirão um parser específico de DEX/agregador.
- O score atual mede comportamento, não lucro.
- P&L, win rate, drawdown e retorno dependem de preços históricos no instante de cada
  operação; não são inventados nesta versão.
- A simulação registra o sinal e os custos configurados, mas ainda não marca posições a
  mercado.

## Próximo marco recomendado

Integrar preços históricos por timestamp e construir o ledger de posições FIFO. Isso
desbloqueia P&L realizado/não realizado, win rate, drawdown e um Wallet Score financeiro.

## Estrutura

```text
app.py                 dashboard
src/solana.py          cliente RPC e parser
src/database.py        schema e acesso SQLite
src/services.py        sincronização e paper trading
src/analytics.py       métricas e score
tests/test_parser.py   teste do parser
```

