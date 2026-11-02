# Pré-registro — POS-RUNNER-V3 ("segunda corrida pós-queda", `56762db29cd6`)

Status: **PRE-REGISTRADO** antes de qualquer coleta/cálculo real sobre dados novos. Regra congelada
no momento deste documento (commit que o introduz); nenhum parâmetro pode mudar no meio da coleta —
mudar parâmetro = versão nova, nunca um retune desta mesma validação (mesma disciplina de
`docs/pos-runner-v1/PROTOCOLO_VALIDACAO.md`/`PLANO_ANALISE_PREREGISTRADO.md`).

**Proveniência das regras:** a cadeia runner→queda→base→pavios→gatilho e os valores de limiar vêm de
uma síntese do "professor" repassada via Gemini ao operador — **a verificar**, nunca tratada como
fonte peer-reviewed ou como garantia de mecanismo real. Este pré-registro trata a regra como uma
hipótese a testar, não como verdade estabelecida.

## O que é / o que não é

POS-RUNNER-V3 é uma estratégia NOVA (`ParamsV3`, hash próprio `56762db29cd6` —
`signals_mvp/pos_runner/params_v3.py`/`pos_runner_v3.yaml`), **nunca** um retune de V1
(`279b79ffa3f0`) ou V2 (`d57b4331d51d`): os dois hashes anteriores ficam intocados (confirmado por
teste, `tests/test_pos_runner_v3.py: test_v1_and_v2_hashes_are_untouched_by_the_v3_refactor`). O
detector/simulador são os MESMOS de V1/V2 (`detector_v1.py`/`simulate_v1.py`, **zero código novo de
detecção**) — a V3 só muda 3 valores de parâmetro (`zone_min_candles=4`, `age_window_days=(0,36500)`,
`drop_max=0.96`; ver `pos_runner_v3.yaml` para a justificativa de cada um) e adiciona covariáveis de
medição (`pos_runner_v3.py`, funções puras, nunca influenciam ENTRADA/saída).

**Confirmado por regressão** (`tests/test_pos_runner_v3.py`): `ParamsV3` com os VALORES da V1
reproduz byte-a-byte os eventos da V1; `zone_min_candles=4` arma uma caixa curta (4 candles, 1
pavio) que `zone_min_candles=12` nunca armaria nos mesmos candles; um pool de ~1 dia é aceito pela
V3 e rejeitado pela V1 por idade; um fundo de caixa abaixo de `L_bc` é rejeitado pelas DUAS (a
invariante `trough >= L_bc`, `detector_v1.py: _kills_wave`, é compartilhada, a V3 nunca precisou de
regra nova para isso).

## Métrica e amostra (hipótese primária)

Mesma métrica de `PLANO_ANALISE_PREREGISTRADO.md`: `dif_pareada = R_sinal − R_controle_médio`
(`pr_baseline`, baseline pareada N=10 por ENTRADA real, reusando `candidatos_elegiveis`/
`sortear_controles`/`simular_controle` de `evidencia.py` sem nenhuma mudança — a V3 só passa
`versao="v3"` e seu próprio `entry_id`, as duas tabelas `pr_trajetoria`/`pr_baseline` já são
genéricas por `(versao, entry_id)`). R é sempre `lucro_líquido_% / risco_%`.

- Unidade de análise: 1 ENTRADA real fechada com `dif_pareada` já calculado (controles E sinal
  resolvidos). `n` conta **tokens distintos** (mint), mesma convenção de V1/V2.
- **N = 30 tokens distintos** fechados decide a hipótese primária (nunca menos).
- V3 nunca se mistura com V1/V2 na mesma análise (coluna `versao='v3'` em `pr_trajetoria`/
  `pr_baseline`, tabelas próprias `pr3_signals`/`pr3_filtrados` quando a integração ao vivo for
  escrita — ver "Pendente" abaixo).

## Hipótese primária, única confirmatória

**H1(V3):** a média de `dif_pareada` da V3 é > 0 (o sinal real da V3 supera, em média, a baseline
pareada do mesmo token).

**Decisão (fixa, nesta ordem — MESMA robustez da Emenda 1 de `PLANO_ANALISE_PREREGISTRADO.md`,
3 desfechos, nunca PASS/FAIL binário):**

1. **Futilidade antecipada:** com n = 15 tokens distintos resolvidos, se a média de `dif_pareada`
   estiver < −0,5 R, H1(V3) para aqui — `FUTIL`.
2. **Decisão em n = 30** (sem ter parado por futilidade) — `EDGE_PROVISORIO` só se **todos** os 4
   critérios da Emenda 1 forem verdadeiros:
   - (a) limite inferior de 90% do bootstrap em blocos (10.000 réplicas, seed `20_261_102`) > 0, nos
     dois eixos (dia E token);
   - (b) estimativa pontual da média de `dif_pareada` > 0 após remover o único maior ganho
     individual (leave-one-out);
   - (c) teste de permutação por inversão de sinais sobre a média das diferenças pareadas, p < 0,10;
   - (d) sobrevive a 3% de custo adicional por perna (além do `CostModel` oficial) — estimativa
     pontual > 0.
   Qualquer outro caso (falha (b) ou (c), sobretudo) é **sempre** `INCONCLUSIVO`, nunca "refutado".
3. **Correção Bonferroni entre V1 e V3** (PEDIDO explícito do Passo 1): V1 e V3 correm em paralelo,
   cada uma com sua própria hipótese primária confirmatória sobre a MESMA fonte de candles/mercado
   — para controlar o erro familywise de duas hipóteses primárias simultâneas, cada uma usa
   **α = 0,025** (0,05/2) em vez de 0,05 nos testes de hipótese acima (o limite de 90% do bootstrap
   em (a) vira limite de **95%** unilateral; o p-valor de (c) continua comparado a 0,10 — esse
   critério já é parte da robustez (b)-(d) da Emenda 1, não do α primário, e não é recalculado aqui).
   V2 não entra nessa correção (não tem hipótese primária própria neste momento — é "SOMENTE V2
   experimental", nunca testada isoladamente nos docs existentes).
4. Esta validação por si só não promove nada a `VALIDADA` — exige os 3 passos do registro de
   hipóteses do repositório (PASS pré-registrado, PASS numa replicação fresca, líquido de custos
   positivo no Gate 2), conforme `CLAUDE.md`.
5. **Nenhum parâmetro de `ParamsV3` pode ser ajustado depois de ver qualquer dado desta coleta** —
   mudar `zone_min_candles`/`drop_max`/`age_window_days`/qualquer outro campo é uma versão nova, com
   pré-registro próprio, nunca um retune desta mesma validação.

## Estratos exploratórios (Holm sobre os testados, nunca confirmatórios)

Cada estrato testa, dentro do grupo nomeado (nunca grupo A contra grupo B), se a média de
`dif_pareada` é > 0, MESMO bootstrap por dia (10.000 réplicas, mesma seed), p-valor bootstrap de uma
ponta `p = P(média_bootstrap <= 0)`. **Grupo com n < 10 tokens distintos nunca é reportado** (nem
conta p-valor, nem entra no Holm) — mesma trava de `PLANO_ANALISE_PREREGISTRADO.md` H2-H8.

1. **caixa >= 12 candles** vs < 12 (campo `caixa_candles`);
2. **caixa >= 48h** vs < 48h (campo `caixa_horas`);
3. **idade 2-7 dias** vs fora dessa janela (campo `idade_dias` — a MESMA janela que V1 usa como
   filtro real; aqui é só rótulo descritivo, a V3 nunca filtra por idade);
4. **queda 90-94%** vs fora dessa faixa (campo `queda_pico_pct`);
5. **MC da base <= 200k** vs > 200k (campo `mc_base`, a mesma covariável `S` do detector);
6. **gatilho**: `reacao_suporte` vs `rompimento` (campo `gatilho_tag`, um sinal com os dois tags
   conta nos dois grupos — mesma convenção não-exclusiva de H2 em V1/V2);
7. **descomunal**: `razao_corpo_descomunal >= 0,25` vs `>= 0,50` vs abaixo de 0,25 (3 grupos, campo
   `razao_corpo_descomunal` — corpo do candle de rompimento sobre `P_peak - R`);
8. **possível clone**: `possivel_clone == True` vs `== False` (campo `possivel_clone`).

**Correção Holm:** os p-valores de todos os grupos com n >= 10 (até 2+2+2+2+2+2+3+2 = até 17 testes)
formam UMA família; Holm-Bonferroni step-down (ordena p-valores crescente, compara o i-ésimo menor
contra α/(m−i+1), α = 0,05 — os estratos são discovery, não a hipótese primária, então usam o α
cheio, nunca o α/2 da seção anterior) sobre essa família completa. Um estrato que passa o Holm é
**candidato**, nunca validado — exige pré-registro específico, replicação fresca e Gate 2 próprios,
igual a qualquer hipótese derivada.

## Covariáveis gravadas por sinal (sempre, nunca só nos estratos acima)

`caixa_candles`, `caixa_horas`, `idade_dias`, `queda_pico_pct`, `mc_pico` (=`P_peak`), `mc_base`
(=`S`), `razao_base_l_bc` (=`S/L_bc`), `n_pavios` (=`n_testes`), `profundidade_pavios_pct`, `gatilho`
(reação/rompimento), `possivel_clone`, `tempo_desde_pico_h`, `corpo_power_candle_atr`,
`razao_corpo_descomunal`, `posicao_pct_supply` (tag `posicao_pct_supply_alerta` quando > 1,5% —
PEDIDO explícito; nunca altera o tamanho de posição real, que continua `mao_fixa_usd`/`posicao_frac`
de `ParamsV3`, idênticos à V1). Implementação pura testada isoladamente:
`signals_mvp/pos_runner/pos_runner_v3.py` (`calcular_covariaveis_v3`), `tests/test_pos_runner_v3.py`.

## Janela de trajetória (72h vs 7 dias) — decisão condicionada ao Passo 0e

O Passo 0 (resposta separada, mesma entrega) levanta que `evidencia.py` fecha MFE/retornos em 72h
fixas (`JANELA_FECHAMENTO_H`) e que não há, nesta leitura de código, uma medição pronta de quantos
sinais reais levam mais de 72h para alcançar o "topo anterior" (P_peak) — isso exige consultar
`pr_trajetoria`/`pr_bars` reais na VM, que este checkout não tem. **Decisão pré-registrada:** se essa
medição (a rodar na VM, nunca fabricada aqui) mostrar uma fração relevante de sinais (V1 ou V3) cujo
`mfe_h` ainda está subindo perto do corte de 72h (proxy de "não deu tempo"), a janela da V3
especificamente passa a 7 dias (168h), usando polling frio (ainda não implementado — ver FASE 2 em
`docs/pos-runner-v1/ESTADO_2026-11-02.md`) só para os candles extras que isso exige. **Isto nunca
pára V1/V2** (que continuam em 72h, regra própria intocada) e nunca é aplicado retroativamente a
sinais já resolvidos em 72h — é uma extensão de JANELA (amostragem/medição), nunca uma mudança da
regra de detecção/entrada/stop da V3.

## Pendente (próximo commit, fora do escopo coberto por este pré-registro em si)

O núcleo testado por este pré-registro (`ParamsV3`, detector/simulador compartilhados,
`pos_runner_v3.py` covariáveis puras) está implementado e testado nesta entrega
(`tests/test_pos_runner_v3.py`, 17 testes). **Ainda não implementado, para não arriscar pressa numa
entrega cientificamente sensível:**

- integração ao vivo em `live.py` (`_detector_v3`/`_entry_v3`, persistência em `pr3_signals`/
  `pr3_filtrados` — tabelas a criar, schema espelhando `pr1_signals` + as covariáveis acima),
  silenciosa por padrão (resumo diário, sem alerta por sinal), `SEM_V3=1`/`V3_ALERTAS=1`;
- script offline de retro-coorte da V3 sobre `pr_bars`/candidatos congelados (rotulado "retro,
  exploratório", MESMA disciplina de `avaliar_candidatos_retro.py`) — o "lote 2" da coorte só pode
  ser congelado DEPOIS do hash `56762db29cd6` existir num commit, condição já satisfeita aqui;
- módulo de análise estratificada (Holm sobre os 8 estratos acima) — estende
  `signals_mvp/analise/condicional.py`, mesmo padrão de `/analise v1|v2`;
- RSS delta atribuível à V3 (a amostragem existente, `pr_rss_amostra`/FASE 1d, mede RSS total do
  processo + pools ativos; um delta especificamente da V3 precisa de uma comparação controlada
  com/sem `SEM_V3`, não um número que se possa calcular sem rodar as duas condições);
- polling frio derivado do menor `zone_min_candles` entre as versões (V3 = 4): permanece atrás de
  `POS_RUNNER_TIERS=1` (FASE 2, ainda não liberada — ver `ESTADO_2026-11-02.md`), mas quando essa
  fase for implementada o cálculo do intervalo PRECISA considerar o 4 da V3, não só o 12 de V1/V2.

Nenhum destes itens pendentes muda o hash `56762db29cd6` nem invalida os testes de regressão já
commitados — são aditivos, e serão pré-registrados/testados na mesma disciplina quando entregues.

## Testes e hashes

`tests/test_pos_runner_v3.py` (17 testes) + suite completa — ver resposta do operador para a
contagem exata desta entrega. Hashes: `ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d` (intocados),
`ParamsV3=56762db29cd6` (novo, próprio).
