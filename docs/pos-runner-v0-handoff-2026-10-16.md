# Handoff — POS-RUNNER-V0 (estratégia pós-runner) — 2026-10-16

Branch `signals-mvp` (espelho em `claude/pensive-wright-62usq8`, PR #6). Modo PAPER / READ ONLY: nenhuma chave, nenhuma
assinatura, nenhuma ordem. Kernel Rust, branch do H2, `benchmarks/sig_fast_v0/` e `artifacts/sig_fast_h2_*` intocados
(a enumeração de migrações por âncora foi COPIADA para `signals_mvp/pos_runner/solana_rpc.py`, com a origem citada).

## 1. Onde está cada entrega do handoff (§7)

| entrega | estado |
|---|---|
| Passo 0 — relatório com os 5 gráficos, ANTES de congelar | **feito e enviado** — `signals_mvp/pos_runner/passo0_relatorio/relatorio_passo0.md` (+ PNGs, medidas, dados brutos com SHA256) |
| Pré-registro `POS-RUNNER-V0` commitado ANTES do backtest (depois do OK) | **rascunho commitado** — `docs/pos-runner-v0-preregistration-DRAFT-2026-10-15.md`; linha `RASCUNHO` no registro. Vira `PRE-REGISTRADO` (com o hash da config) só depois do seu OK |
| Parte A — backtest sem viés (cobertura → discovery → holdout) | **código pronto e testado, NÃO executado** — `signals_mvp/pos_runner/parte_a/`. O próprio código recusa rodar enquanto o pré-registro não estiver `PRE-REGISTRADO` com o hash certo e com o holdout selado e commitado |
| Parte B — sinal ao vivo no bot, com passo a passo | **ligada** (config em rascunho) — `signals_mvp/pos_runner/live.py`; passo a passo no `signals_mvp/README.md`, seção "POS-RUNNER ao vivo" |

## 2. O que preciso de você (o portão)

Do relatório do Passo 0 (as respostas destravam o congelamento):

1. Os gráficos são os tokens do professor? Em especial **SOLCAT** (MC ~30k hoje, não ~575k) e **ZILLIONS** (qual trecho/data?).
2. Em cada gráfico, qual é o setup do professor (número da entrada `#n` ou a data do rompimento)?
3. **SOLCAT**: a base ficou ~25% abaixo do `L_bc`. "Fundo acima da bonding curve" vale sem tolerância (SOLCAT fica de fora)?
4. "Tokens de 2–7 dias em fase 2": idade desde a graduação ou tempo na fase 2? Pode ficar só como atributo (proposta)?
5. Saída por exaustão: "+50% desde a entrada" (handoff) ou "perto do último topo"?
6. Aprova a proposta (corpos, queda até 95%, martelo ≥ 1,5× corpo, alvo no topo real)?
7. Parte A: horizonte de 14 dias depois da graduação e mínimo de 20 trades no holdout — ok?
8. O POS-RUNNER ocupa o "caminho 2" da regra de parada do programa?

Da Parte B (interpretações que tomei; diga se alguma está errada):

9. **👀 WATCHLIST** sai quando a fase 2 fica **armada** (caixa com tamanho mínimo e ≥ 1 wick no suporte), não no
   instante em que a queda chega a 80% — só a partir daí existem S, R e nº de wicks, que o handoff pede no alerta.
10. **Só o 1º setup de cada token/timeframe gera 👀/🟢** (`so_primario: true`); reentradas viram só paper (no CSV).
    O 5m gera muitas micro-caixas; com `false` você recebe todas.
11. **Radar**: entra quem está com **MC ≥ 300k no momento** em que aparece nas listas do GeckoTerminal (trending + top
    volume de PumpSwap/DAMM v2/Raydium) ou nos pools novos do v0. Runner que aconteceu com o bot desligado não entra
    depois. Quer um comando para você pôr um token no radar à mão?

## 3. Como a Parte B funciona (resumo; detalhe no README)

- Mesmo detector, simulador, custos e conversão para USD do backtest. Candle consumido só **fechado** (+90 s para o
  GeckoTerminal indexar) e **congelado** no SQLite: reiniciar o bot refaz exatamente o mesmo estado.
- Um token só entra no radar depois da **prova on-chain** de que o pool nasceu da migração de um dos 3 launchpads, para
  aquele mint (mesmo critério da enumeração da Parte A; roda numa thread própria, com o RPC público ou o seu em
  `POS_RUNNER_RPC_URLS`).
- Chamadas ao GeckoTerminal saem de uma fatia reservada do orçamento do v0 (`chamadas_por_ciclo`, padrão 3); candidato do
  v0 continua com prioridade, mas o POS-RUNNER nunca fica sem pelo menos 1 chamada por ciclo.
- Alertas: 👀 (fase 2 armada), 🟢 (entrada + mini-gráfico + Axiom), ⚪ (candle absurdo: não entrar), 🔴 (invalidado),
  🟡 (saída sugerida, como resposta ao 🟢), 📊 (resultado do paper com custos e base pareada).
- Paper A/B de **toda** entrada (custo 1× e 2×) e base pareada (até 5 outros runners do radar na mesma idade, mesmo
  colchete). CSVs `dados\pos_runner.csv` (colunas exatas do handoff) e `dados\pos_runner_detalhe.csv`.
- **Regra científica**: enquanto a config estiver em rascunho, o paper ao vivo é só operacional. Mudar parâmetro
  depois de olhar resultado dele = ajuste em dado de resultado (proibido); linhas de outra `versao_config` ficam fora de
  qualquer avaliação (§3.1 do rascunho do pré-registro).

## 4. Verificações feitas nesta sessão

- 236 testes offline (`python -m unittest discover -s signals_mvp/tests -t .`) em Python 3.13 e 3.10 (o mínimo do
  README; sem matplotlib o teste do gráfico é pulado). Os novos usam respostas **reais**: a lista *trending* do
  GeckoTerminal e as 3 transações de migração (pump.fun/SOLCAT, LaunchLab/ZILLIONS, DBC/FLAME).
- Testes da Parte B: fluxo completo (descoberta → linhagem → carga → 👀 → 🟢 → paper → 🟡 → 📊 → CSV), candle em
  andamento nunca consumido, reinício sem alerta repetido, bot desligado no rompimento (paper gravado, sem alerta
  velho), histórico antes do radar fora do paper, orçamento (nunca passa da fatia nem toca as chamadas guardadas), 429,
  erro de um pool sem travar os outros, multi-timeframe com cotação em SOL, integração com o engine.
- Teste de fumaça contra **GeckoTerminal e RPC reais** (somente leitura, sem Telegram): ver §6.
- **Acompanhamento +60 min do v0** refeito contra o OHLCV real nos 16 sinais do teste ao vivo de 13/10, pelo caminho real
  do engine: 16/16 fechados e **0 divergência** numa conferência independente (MC +5/+15/+60, máx., mín.). Achado: o 1º
  open do minuto seguinte ficou a ~7% (mediana) do preço da foto da decisão, e a mais de 20% em 6 de 16 — registrado no
  README do v0 como limitação medida.

## 5. Bugs achados e corrigidos

- **Config do v0**: o endereço do USDT da Solana em `ativos_referencia` estava errado (GeckoTerminal responde 404); o
  correto é `Es9vMFrz…NkY11McCe8BenwNYB`. Isso gera uma **nova versão do config** (`versao_config` muda).
- **Carga de candles com poucas chamadas por ciclo podia nunca terminar** (páginas vazias de confirmação não entravam no
  checkpoint). Corrigido no `OhlcvStore` (usado também pela Parte A): checkpoint de toda página e início alinhado ao candle.
- **Linhagem**: paginar o histórico do próprio pool não serve para pool quente (DOPE: ~500 transações/s logo depois da
  graduação). A conferência agora lê a conta-chave do launchpad numa janela de ±10 min e abre primeiro a transação mais
  próxima da criação.
- URL de RPC (que pode levar chave) não aparece mais em log: só o host.

## 6. Teste de fumaça contra as APIs reais

(preenchido abaixo depois da execução)

## 7. Limitações declaradas

- Candle não mostra a ordem dos preços dentro dele (stop e alvo no mesmo candle = stop). Entrada do paper = open do candle
  seguinte ao sinal; o clique real chega depois do alerta (pesa mais no 5m).
- Fee dos pools Raydium CPMM e Meteora DAMM v2 não confirmada (1% conservador por perna); supply atual (queima posterior
  distorce o passado); cotação/USD pelo fechamento horário anterior.
- Cobertura da enumeração da DBC: só a config de DAMM v2 `A8gMrEPJ…` (amostra de 78 migrações: todas com ela; migração
  para DAMM v1 não coberta). A LaunchLab só por `MigrateToCpswap`.
- O RPC público é lento e limita `getTransaction`; neste ambiente (IP de saída compartilhado) ele recusou bastante. Um RPC
  gratuito seu deixa a entrada no radar muito mais rápida.
- Windows real e Telegram real não testados nesta sessão (o cliente do Telegram é o mesmo do v0, com `sendPhoto` novo).

## 8. Próximos passos (só depois do seu OK)

1. Ajustar `pos_runner_v0.yaml` às respostas, congelar, pôr o hash no pré-registro, trocar o status para
   `PRE-REGISTRADO` e atualizar a linha do registro — tudo no mesmo commit, antes de qualquer coleta.
2. `python -m signals_mvp.pos_runner.parte_a.cli plano --congelamento <data>` → commit.
3. `selar-holdout` → commit da selagem (hash) ANTES do discovery.
4. `discovery` → `escolher` → commit da escolha → `holdout` (só se o discovery der candidato) → `relatorio`.
