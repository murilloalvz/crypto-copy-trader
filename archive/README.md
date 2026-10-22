# archive/ — pesquisa histórica (pausada, não apagada)

Esta pasta guarda o que já foi escrito neste repositório ANTES do bot de sinais atual
(`signals_mvp/`) e que não tem nenhum acoplamento com ele — nenhum teste, import ou script de
`signals_mvp/` depende de nada aqui dentro. Nada foi apagado: cada subpasta abaixo preserva o
histórico de commits de onde veio (movida com `git mv`), só reorganizada para não poluir a raiz
do projeto. Ver `docs/LIMPEZA_MANIFESTO.md` para a tabela completa da decisão (manter / arquivar /
remover) item por item.

## O que tem aqui

- **`benchmarks/`** — 71 experimentos versionados (um por hipótese) do programa de pesquisa
  anterior ("Opportunity Intelligence Engine": burst de lançamento, Signal Plane, qualidade de
  carteira, estrutura de mercado, etc.). As duas subpastas que continuam ativas
  (`benchmarks/sig_fast_v0/` e `benchmarks/integrated_market_signal_plane_v1/`, o kernel Rust)
  **não** foram movidas — continuam na raiz de `benchmarks/`.
- **`docs/`** — a documentação desse mesmo programa (~200 arquivos). Os documentos que o
  `CLAUDE.md` da raiz ainda cita como autoridade ativa (mapa de migração, registro de hipóteses,
  Gate 2, o holdout `native-participant-quality-holdout-v1`, o incidente de capacidade da Research
  Plane, a documentação do `sig_fast_v0`) continuam em `docs/`, não aqui.
- **`app/`** — o dashboard Streamlit do copytrader anterior (`app.py` + `src/`), com seu próprio
  `requirements.txt` (streamlit/pandas/plotly) para quem quiser rodá-lo de novo.
- **`tests/`** — a suíte de testes desse programa anterior (nunca testou `signals_mvp/`).
- **`scripts/`** — os ~150 scripts de linha de comando da raiz (coleta de carteira, pesquisa de
  rota, replays causais, etc.) + `start-monitor.ps1`.
- **`research/`**, **`wallets/`** — dados e notas de pesquisa pontuais do mesmo programa.
- **`ci_antigo/`** — os workflows do GitHub Actions que testavam só esse código (continuam aqui
  como registro; não disparam mais, já que não estão em `.github/workflows/`).

## Por que isso não é lixo

É pesquisa real, com commits reais — só não é o produto que este repositório documenta hoje
(`signals_mvp/`, o bot de sinais em modo PAPER). Mantido por honestidade histórica: resultados
negativos e trabalho pausado fazem parte do registro, não são escondidos.
