# Handoff — POS-RUNNER-V0 (Parte A) — 2026-10-19

Branch `signals-mvp` (espelho em `claude/pensive-wright-62usq8`, PR #6, draft, CI verde). Modo PAPER / READ ONLY
inalterado. Continua de `docs/pos-runner-v0-handoff-2026-10-16.md` (congelamento) — este cobre só o que mudou
desde então: emendas §13/§14, ferramentas de diagnóstico e os 2 diagnósticos em aberto.

## 1. Estado atual (resumo de 1 linha por item)

| item | estado |
|---|---|
| Hash do plano | `7e6fdc65d31f` (era `8a2387a3e185` antes do §13) |
| Hash da config | `0de2333a7f63` (inalterado desde o congelamento) |
| Holdout selado | **válido, intocado** — 1200 janelas, 27349 graduações, `hash_pools 3f648e95...` |
| Discovery (checkpoint local desta sessão) | vazio (`stage1`/`stage2`/`setups`/`trades` com 0 linhas) |
| Discovery (checkpoint do operador, Windows) | em andamento — rodada 1 (1h) já rodou, achou **0 setups primários** em 695 runners (691 depois confirmados meteora_dbc) |
| Bug suspeito nos runners DBC | **em investigação, NÃO confirmado, NADA corrigido** |

## 2. O que mudou desde 16/10 (emendas, todas cegas a resultado)

- **§13 (17/10)** — `discovery_start_override`: início do discovery recortado de 22/04 para 05/06 (motivo: o
  PC do operador não fica ligado 24h; o início antigo ficava colado no limite móvel de 180 dias do GT).
  Discovery 95→51 dias, 4560→2448 janelas (-46%). Embargo/holdout **byte-a-byte iguais** (testado). Limitador
  do GT: teto 20→26/min + jitter de 1,5s.
- **§14 (19/10)** — discovery dividido em 2 **rodadas por timeframe** (objetivo: 1º resultado concreto mais
  cedo, sem cortar nenhuma das 24 combinações): rodada 1 = só 1h (8 combinações), para sozinha ao bater 60
  setups; rodada 2 = 5m+4h juntos (16 combinações), OBRIGATÓRIA em seguida. `escolher`/`holdout` agora
  produzem até 2 candidatos (1 por rodada), declarados como **2 testes de hipótese** no relatório (nunca 1
  escolha sobre as 24 juntas). Comando novo `funil --periodo {discovery,holdout}`: só contagens (pools,
  estágio 1, runners, estágio 2 por tf/status, setups por tf/launchpad/hora BRT), zero chamada de rede,
  funciona com download parcial.
- **`funil_atrito.py`** (commit `2bb0cf2`, `signals_mvp/pos_runner/parte_a/funil_atrito.py`) — diagnóstico
  avulso (não é comando oficial do `cli.py`): re-roda o detector sobre os candles já cacheados (zero rede por
  padrão) porque os eventos de fase (RUNNER/FASE2/WATCHLIST/TESTE/ONDA_INVALIDA) nunca são persistidos — só
  `ENTRADA` vai pro banco. Mostra o funil completo por tf/launchpad, distribuição de `P_peak`, contagem de
  `L_bc` nulo/zero, distribuição de idade das entradas brutas.

Nenhuma regra primária, grade, atributo secundário ou limiar mudou em §13/§14. Nenhum restamp foi necessário em
§14 (código de orquestração, não toca `Params`/`PeriodPlan`).

## 3. Diagnóstico 1 (18–19/10) — por que 0 setups primários na rodada 1

**Achado, com evidência (controle positivo rodado offline nos 5 exemplos do professor, candles reais
cacheados, zero rede):** o detector dispara `ENTRADA` com frequência (62 entradas brutas em 29 combinações
válidas), mas quase todas caem **fora da janela de idade 2–7 dias desde a CRIAÇÃO** do token — o rompimento só
ocorre dias depois da graduação, e a idade é medida desde a criação (decisão intencional do operador), não
desde a graduação. Zona (queda 80–90%) e zona madura (watchlist) disparam quase sempre; quem mata quase tudo é
o filtro de idade. **Hipótese líder, não confirmada nos 695 runners reais** (preciso do checkpoint do operador
ou da saída do `funil_atrito.py` nele).

Também auditado (sem bug): ordem cronológica dos candles (`Detector.update` levanta erro se fora de ordem),
fuso (tudo epoch UTC puro, sem conversão de fuso em `age_days`), fórmula de `L_bc` (igual nos 3 launchpads).

## 4. Diagnóstico 2 (19/10) — MC absurdo nos runners Meteora DBC — EM ABERTO

O `funil_atrito.py` do operador mostrou `P_peak` impossível em DBC (mediana ~665M USD, p90 ~4,9bi) contra
pump.fun plausível (349k–2,4M). 690/695 runners são DBC.

**Descartado** (auditoria de código + 3 chamadas reais ao GT, dentro do orçamento):
- supply/decimals: vêm do RPC (`getTokenSupply`, já ajustado por decimals), mesma função nos 3 launchpads;
- quote hardcoded por launchpad: não existe — e 99,87% dos DBC do holdout (17.838/17.861) são cotados em
  SOL/USDC/USDT, igual ao pump.fun — a hipótese inicial ("moeda de cotação diferente") não é a causa dominante;
- 3 pools reais verificados contra `/pools/{addr}` do GT (1 FLAME + 2 DBC do holdout): `base_token == mint`
  nos 3 (sem inversão), decimals=6 confirmado num deles, FDVs de $962 a $19,3M — nenhum reproduziu a escala
  de centenas de milhões/bilhões relatada.

**Não descartado** (sem orçamento de chamada pra fechar):
1. `OhlcvStore.history(pool, tf, ..., currency="token")` nunca passa `side` explicitamente (default `"base"`)
   — assume sempre que o mint é o lado "base" do pool, sem verificar; confirmado certo em 3/3 amostras, mas
   3 é pouco pra descartar nos 690;
2. qualidade do candle histórico do GT especificamente pra pools Meteora DAMM v2 (liquidez concentrada é
   estruturalmente diferente do AMM simples do PumpSwap) — não testado, ficou sem orçamento de chamada.

**Nada foi corrigido.** Diffs propostos, aguardando revisão do operador:
1. Resolver `side` real por pool (1 chamada `/pools/{addr}`, cacheável) em vez do default silencioso;
   sem dado → status explícito `"sem_dado: lado do pool"`, nunca um palpite.
2. Gravar supply/decimals/side usados em `stage1.info` (permite auditar em SQL puro, sem re-rodar nada).
3. Extender `funil_atrito.py` com uma tabela "top-N por `max_mc`" (pool/mint/supply/decimals/quote/preço/MC/L_bc).

**Impacto em hash se confirmado e corrigido:** nenhum em `Params`/`PeriodPlan` (não é campo de config, é código
de conversão) — mas `stage1`/`stage2`/`setups`/`trades` dos pools DBC afetados ficariam inválidos e precisariam
reprocessar (mesmo padrão dos achados de parser de pump.fun, §11/§12 do pré-registro).

## 5. Pendente do operador (nessa ordem)

1. Rodar (ou mandar o checkpoint pra eu rodar) `funil_atrito.py --periodo discovery --tf 1h` e a query de
   `L_bc` por launchpad (dada na resposta do Diagnóstico 2) — fecha os itens 1, 2, 4 e 5 em aberto.
2. Com isso: decidir se o bug de MC/`side` é real antes de deixar a rodada 2 (5m/4h) ou o `escolher` seguirem
   — um MC/`L_bc` errado em 690/695 runners contamina qual combinação "ganha" o discovery.
3. Se confirmado: eu trago o diff pra revisão (não aplico sem OK), reprocesso só os pools DBC afetados
   (`Store.reprocess_graduation`-style, nunca editar o SQLite na mão), e re-valido antes de continuar.
4. Se não confirmado: seguir o fluxo normal — `discovery --rodada 2` → `escolher` → commit →
   `holdout` → commit → `relatorio`.

## 6. Comandos (Windows, raiz do repo, venv ativo)

```powershell
git pull
python signals_mvp\pos_runner\parte_a\funil_atrito.py --periodo discovery --tf 1h
python -m signals_mvp.pos_runner.parte_a.cli discovery --rodada 2   # SO depois do item 5.2 decidido
```
