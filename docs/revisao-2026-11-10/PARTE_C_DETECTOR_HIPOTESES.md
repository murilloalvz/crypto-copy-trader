# Rodada 16 — Parte C: detector e hipóteses

Auditoria read-only. Achado mais importante: **o teste de RECALL pedido (B9, exemplos do
professor) não pode ser executado nesta sessão nem na forma atual** — o CSV de exemplos só contém
um placeholder, nunca os casos reais (Aoin/Solana Cat/Apil) que o operador deveria ter preenchido, e
mesmo preenchido o script exige o banco ao vivo (inexistente neste checkout). Segundo achado
importante, de impacto potencialmente maior: **a hipótese H1 (a única confirmatória do projeto,
porta de entrada para "EDGE_PROVISORIO"/dinheiro real) nunca foi migrada para o motor de R no
horizonte fixo** (`horizonte_fixo.py`) que o próprio projeto construiu e documentou como a correção
para o viés de excluir sinais não resolvidos por regra — H1 continua rodando sobre a fonte legada,
que descarta silenciosamente `perdido_offline`/`aberto`/`descontinuado`.

---

### [P1] Teste de RECALL (B9) não preenchido pelo operador — e não executável nesta sessão mesmo se preenchido
- **Evidência**: `signals_mvp/scripts/exemplos_v3_modelo.csv` tem exatamente 2 linhas: o cabeçalho
  (`token_ou_pool,inicio,fim,esperado,nota`) e **uma linha PLACEHOLDER** (`PLACEHOLDER_preencha_com_
  symbol_ou_endereco_do_pool,2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,sinal,PLACEHOLDER -- linha de
  exemplo do FORMATO, nunca um caso real; apague antes de rodar`). `grep -rln "exemplos_professor\|
  Aoin\|Solana Cat\|Apil" .` não encontrou NENHUMA referência a esses nomes em nenhum arquivo deste
  repositório (código, docs, CSV) — os exemplos citados no pedido do operador nunca foram
  registrados em lugar algum do repositório, nem como texto nem como dado.
  `signals_mvp/scripts/testar_exemplos_v3.py` (linhas 1-24) é exatamente o script certo para isto
  (`--db <banco> --exemplos <csv>`), mas precisa de `--db` apontando para um banco com `pr_pools`/
  `pr_bars` já populados para os pools em questão — **banco que não existe neste checkout**.
- **Impacto nas conclusões**: o teste de recall pedido pelo operador (confirmar que a V3 realmente
  reconhece um caso conhecido como sinal e rejeita outros 2 conhecidos como descarte) nunca foi
  feito, em nenhuma rodada anterior — é uma lacuna real na validação do detector, não só desta
  sessão.
- **Correção proposta**: o operador precisa (1) preencher
  `signals_mvp/scripts/exemplos_v3_modelo.csv` (ou uma cópia, fora de `dados/`) com as linhas reais:
  `token_ou_pool` = symbol ou endereço do pool do Aoin (sinal esperado) e dos 2 descartes
  (Solana Cat, Apil), `inicio`/`fim` = janela ISO8601 em que o padrão deveria ter sido reconhecido,
  `esperado` = `sinal`/`descartar`; (2) rodar `python -m signals_mvp.scripts.testar_exemplos_v3 --db
  <caminho do banco real> --exemplos <esse csv>` **na VM** (onde o banco com esses pools existe) ou
  enviar um snapshot do banco (ou só as linhas de `pr_pools`/`pr_bars` relevantes) para uma sessão
  futura conseguir rodar aqui.
- **Toca hash/exige restart?**: não — o script é somente leitura e não decide nada, só reporta.
- **Confiança**: alto — busca exaustiva, zero ocorrência confirmada.

### [P1] H1 (a única hipótese confirmatória) nunca foi migrada para o motor de horizonte fixo
- **Evidência**: `signals_mvp/analise/condicional.py:1052-1057` — a função `executar()` (chamada
  pelo comando `/analise [v1|v2|v3]` ao vivo via `pos_runner/live.py:3736`,
  `condicional.executar(self.storage, versao)`) chama `carregar_sinais_e_excluidos(storage, versao)`
  **sem** o parâmetro `horizonte`. Em `carregar_sinais_e_excluidos`
  (`signals_mvp/analise/condicional.py:211-237`), o docstring da própria função admite: "`horizonte=
  None` (padrao) = legado inalterado" — e com `horizonte=None`, a fonte de `dif_pareada` é
  `pr_baseline_resolvidas_com_dif` (linha 232), que por sua vez (`condicional.py:355,864`) só
  considera sinais com `status="fechado"` — **excluindo** por construção `status IN ('aberto',
  'cancelado', 'perdido_offline', 'descontinuado')`. Já o motor `pr_horizonte_fixo`/
  `horizonte_fixo.calcular_r_horizonte` (linha 236, só usado quando `horizonte="72h"`/`"7d"` é
  passado EXPLICITAMENTE) foi construído exatamente para resolver sinais que nunca fecharam por
  regra, valorizando a mercado no corte — e **nenhum call site encontrado nesta sessão passa esse
  parâmetro** (`grep -rn "carregar_sinais_resolvidos(" signals_mvp/ --include=*.py` só retorna a
  própria definição da função, nenhum chamador externo).
- **Impacto nas conclusões**: a hipótese H1 — a ÚNICA que pode um dia virar `EDGE_PROVISORIO`/
  `VALIDADA` e liberar dinheiro real segundo o registro de hipóteses — está, hoje, potencialmente
  sujeita ao MESMO viés de sobrevivência que a emenda do horizonte fixo (`EMENDA_2026-11-05_
  HORIZONTE_FIXO_PROPOSTA.md`) foi escrita para corrigir: um sinal que nunca resolveu por regra
  (incluindo `perdido_offline` — tokens abandonados/rugados que pararam de ser atualizados, um
  universo plausivelmente enviesado para PERDAS) simplesmente não entra na média de `dif_pareada`
  que decide H1. O trabalho de construir o motor correto já foi feito (rodadas 11-12) e usado em
  análises EXPLORATÓRIAS (`varredura_v3.py`), mas aparentemente nunca chegou a H1 em si.
- **Correção proposta**: decisão do operador, não uma implementação — mas a pergunta precisa ser
  posta explicitamente: H1 deveria rodar com `horizonte="72h"` (ou `"7d"`) como fonte PRIMÁRIA de
  `dif_pareada`? Se sim, isso é uma mudança MATERIAL no desfecho primário de H1 — precisaria de uma
  emenda formal e nova (nunca um ajuste silencioso, pela própria disciplina do projeto, já que H1 é
  pré-registrada com hash em `PLANO_ANALISE_PREREGISTRADO.md`). Se a decisão for manter o legado
  (por exemplo, por já ter visto resultados sob o legado e não querer trocar o desfecho no meio da
  coleta — "o que já foi visto não pode julgar a si mesmo" correria ao contrário aqui, mudar DEPOIS
  de ver resultado seria o problema), isso precisa ser dito EXPLICITAMENTE em algum lugar, porque
  hoje a divergência entre o motor "correto" documentado e o motor realmente usado por H1 não está
  registrada em nenhum lugar que eu tenha encontrado.
- **Toca hash/exige restart?**: SIM, se a correção for adotada — tocaria o hash de
  `PLANO_ANALISE_PREREGISTRADO.md` (H1 está lá) e precisaria de uma emenda nova. Não toca
  `ParamsV1/V2/V3`. Não exige restart do bot (é código de análise offline).
- **Confiança**: alto para o fato (citações diretas de linha); médio para o "impacto real em
  magnitude" (não tenho dados reais para saber QUANTOS sinais `perdido_offline` existem hoje nem se
  o viés é grande ou pequeno em prática — ver limitação na Parte A).

### [P1] Nenhuma instrumentação de funil para a V3
- **Evidência**: `signals_mvp/scripts/funil_diario.py:81-108` (`montar_funil`) só consulta
  `pr1_signals`/`pr2_signals` (linhas 86-91) e `pr_funil_marcos`/`pr_dormentes` (compartilhados) —
  **nenhuma linha menciona `pr3_signals`**. A V3 (o foco das últimas 6-7 rodadas de pesquisa) não
  tem NENHUMA visão de funil própria neste script.
- **Impacto nas conclusões**: não há como responder, com a instrumentação atual, "quantos pools
  passam cada etapa até um sinal V3" separadamente de V1/V2 — o pedido do operador ("medir quantos
  pools passam cada filtro... quanto da perda é filtro vs oferta") não é respondível para a V3 hoje.
  Além disso, mesmo para V1/V2, o funil é agregado (descobertos→admitidos→runner→caixa→sinal→
  fechado) — não quebra por filtro INDIVIDUAL (`dado_invalido`, teto de idade, `l_bc_ceiling_usd`,
  queda mínima, MC mínimo), então mesmo onde existe funil, não dá pra isolar qual filtro específico
  corta mais.
- **Correção proposta**: estender `montar_funil` com as mesmas consultas para `pr3_signals`, e
  considerar instrumentar contadores por filtro individual (ex.: incrementar um contador em
  `pr_pools`/tabela nova cada vez que `dado_invalido`/idade/MC/L_bc rejeita um candidato — hoje,
  pelo que vi, esses filtros só aparecem como motivo de descarte pontual, não agregados).
- **Toca hash/exige restart?**: não (instrumentação nova, fora do hash de Params).
- **Confiança**: alto — busca direta no código do script.

### [verificado, confiança alta] ENTRADA só decide em candle fechado
- **Evidência**: `_entry_v1`/`_entry_v3` (`signals_mvp/pos_runner/live.py:2618,3059`) recebem `ev:
  EventV1` já emitido por `det.update(bar)` — e `DetectorV1.update()` só processa um `Bar` que já
  chegou completo da fonte (GT/DexPaprika), nunca um candle "em formação" (ver Parte B, achado sobre
  `LAG_S`: candles só são buscados com `b.ts + step <= now - LAG_S`,
  `signals_mvp/pos_runner/live.py:3871`, ANTES de chegarem ao detector). Não há caminho em que um
  candle parcial chegue a `det.update()`.
- **Confiança**: alto.

### [verificado, confiança média] V1/V2/V3 compartilham literalmente o mesmo detector/simulador — pré-registro vs código
- **Evidência**: ver Parte B, achado "Mesmo DetectorV1" — confirmado que `DetectorV1`/`simulate_v1`
  são a MESMA classe/função para as 3 versões, só `Params{V1,V2,V3}` diferem (e o `l_bc`/`grad_ts`/
  `created` por pool, não por versão). Não tive tempo nesta sessão de fazer uma comparação linha a
  linha entre o texto do pré-registro de V1 (hash `279b79ffa3f0`) e cada parâmetro em
  `params_v1.py`, nem o mesmo para V3 (`PREREGISTRO_V3_2026-11-02.md` + emendas vs `params_v3.py`) —
  então não posso afirmar com alta confiança que NÃO há deriva texto-vs-código em nenhum parâmetro
  específico, só que a ARQUITETURA (detector único, params isolados) está correta e documentada.
- **Impacto nas conclusões (para a Parte D/G)**: isto é uma informação importante para o ranking de
  hipóteses — um bug ainda não encontrado no `DetectorV1` em si afetaria V1, V2 E V3 simultaneamente;
  e "3 hipóteses testadas" sobre o mesmo detector-base não são 3 chances independentes de achar edge
  no MESMO mecanismo de entrada, só 3 variações de parâmetro sobre ele. Isso pesa a favor de: se o
  detector-base realmente não tem edge (sinal ≈ passeio aleatório, conclusão já citada pelo
  operador), reparametrizar V1→V2→V3 indefinidamente tem retorno decrescente — vale mais mudar a
  ESTRUTURA (ver Parte G) do que continuar variando parâmetros do mesmo mecanismo.
- **Confiança**: alto para a arquitetura compartilhada; baixo/médio para a fidelidade texto-código
  completa de cada pré-registro (não verificada linha a linha nesta sessão).

### [P2] Filtros que podem estar cortando sinais verdadeiros — não quantificado nesta sessão
- **Evidência**: `l_bc_ceiling_usd` (teto absoluto de sanidade, task #41 do histórico) e o teto de
  idade (`in_age_window`, `detector_v1.py`) existem e cito-os por nome, mas não tive tempo nesta
  sessão de abrir `docs/pos-runner-v1/AUDITORIA_PARAMETROS.md`/a sensibilidade já feita (task #102)
  para extrair os números exatos de corte já documentados.
- **Impacto nas conclusões**: não quantificável aqui — ver limitação abaixo.
- **Correção proposta**: nenhuma — já existe trabalho prévio (`AUDITORIA_PARAMETROS.md`, item 2 de
  sensibilidade) que provavelmente já responde isto; recomendo ao operador reler esse documento
  específico em vez de refazer o trabalho aqui.
- **Confiança**: baixo — não lido nesta sessão por limite de tempo.

## O que NÃO foi possível verificar nesta sessão

- Rodar `testar_exemplos_v3.py` de fato (precisa de exemplos reais do operador + banco real).
- Comparação linha a linha entre o texto de cada pré-registro (V1/V3 + emendas) e os valores exatos
  em `params_v1.py`/`params_v3.py` — só confirmei a arquitetura (detector compartilhado), não cada
  parâmetro individual.
- Números exatos de quantos pools cada filtro específico (idade, MC, L_bc, queda, "4 vs 12 candles"
  se esse conceito existir literalmente em algum lugar — não encontrei essa frase exata no código
  nesta sessão, pode ser uma referência a `box_len`/mínimo de candles na base, que não confirmei)
  corta — precisa do banco ao vivo + tempo para abrir `AUDITORIA_PARAMETROS.md`/sensibilidade já
  escritos.
- Qualquer coisa que dependa de `pr_pools`/`pr_bars`/`pr1-3_signals` reais (inexistentes aqui).
