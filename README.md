# Solana CopyTrader

Laboratório local de **dados on-chain e automação** para monitorar wallets públicas na Solana, persistir atividade em SQLite, identificar swaps e avaliar estratégias por meio de **paper trading**.

O projeto foi construído para explorar integração com blockchain, pipelines de dados e análise quantitativa sem assumir riscos de execução: **não possui chave privada e não envia ordens reais.**

## O que este projeto demonstra

- Integração com Solana via JSON-RPC
- Coleta, transformação e persistência de dados
- Modelagem de métricas e scoring
- Automação de monitoramento
- Simulação de estratégias com paper trading
- Dashboard interativo com Streamlit
- Testes automatizados e código modular

## Funcionalidades atuais

- cadastro e remoção lógica de wallets públicas;
- sincronização de atividade via JSON-RPC da Solana;
- persistência idempotente em SQLite;
- detecção inicial de swaps, transferências de SOL e transferências de tokens;
- métricas de atividade e Wallet Score preliminar;
- paper trades com tamanho, slippage e atraso configuráveis;
- dashboard Streamlit.

## Arquitetura

```text
Solana JSON-RPC
      ↓
Coleta e parsing
      ↓
SQLite
      ↓
Métricas / Wallet Score
      ↓
Paper Trading
      ↓
Dashboard Streamlit
```

## Stack

**Python • SQLite • Solana JSON-RPC • APIs • Streamlit • Análise de Dados • Testes Automatizados**

## Instalação no Windows

Requer Python 3.11 ou 3.12.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

Abra o endereço exibido pelo Streamlit no terminal.

## Configuração

Edite `.env` para configurar o endpoint RPC. O RPC público pode ser utilizado em testes, mas pode limitar requisições em uso contínuo.

Nunca adicione seed phrase ou chave privada ao projeto ou ao repositório.

## Estrutura

```text
app.py                 dashboard
src/solana.py          cliente RPC e parser
src/database.py        schema e acesso SQLite
src/services.py        sincronização e paper trading
src/analytics.py       métricas e score
tests/test_parser.py   testes do parser
```

## Limitações atuais

- O parser inicial usa diferenças de saldo e seleciona o token com maior variação; transações complexas com múltiplos tokens exigem parsing específico.
- O Wallet Score atual mede comportamento e não deve ser interpretado como previsão de rentabilidade.
- Métricas financeiras dependem de preços históricos confiáveis no instante de cada operação.
- O paper trading é uma simulação e não representa execução real ou garantia de performance.

## Próximos passos

- Evoluir o parser de transações e swaps
- Integrar preços históricos por timestamp
- Reconstruir posições e P&L
- Expandir métricas de risco e performance
- Aumentar cobertura de testes

## Autor

**Murillo Lourenço**  
Estudante de Análise e Desenvolvimento de Sistemas na FATEC Sorocaba.

Interesses: Dados, Inteligência Artificial, Automação e aplicações quantitativas.
