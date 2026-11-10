# Rodada 16 — Parte B: correção do pipeline de dados

Auditoria read-only (nenhum código/parâmetro/hash alterado). **Limitação central desta sessão**: o
banco ao vivo da VM (`signals_mvp/dados/estado.sqlite` ou equivalente, com `pr_pools`/`pr_bars`/
`pr1..3_signals` reais) não existe neste checkout — está no `.gitignore` e nunca foi commitado. O
único banco real aqui é `signals_mvp/dados/pos_runner_parte_a/parte_a.sqlite`, cujas tabelas
`stage1/stage2/setups/trades` estão **vazias** (só `graduations`/`windows` têm dados — cache de
enumeração on-chain do V0 antigo, não resultados de trade). Por isso esta Parte B é uma **auditoria
de código** (fato verificado = li o código e confirmei o comportamento; não roda nenhum número real).
O achado mais importante (positivo): **não encontrei lookahead no detector/simulador** em nenhum dos
3 caminhos (vivo/replay/retro). O achado mais importante (negativo): o motor de R@72h
(`horizonte_fixo.py`, usado por `varredura_v3.py` para ao_vivo/retro_lote1/replay_v3) **não aplica o
mesmo veto de candle corrompido** que o caminho ao vivo aplica — o mesmo tipo de falha que já causou
o incidente real do "McRib -561R" documentado no projeto.

---

### [P1] `horizonte_fixo.py` não aplica o veto de candle corrompido que o caminho ao vivo aplica
- **Evidência**: `signals_mvp/pos_runner/horizonte_fixo.py:89` chama
  `simulate_v1(bars, event, params, costs, dex, l_bc, sol_usd_at)` **sem** o parâmetro
  `candle_confiavel`. Em `simulate_v1` (`signals_mvp/pos_runner/simulate_v1.py:96-102,140`), esse
  parâmetro omitido (`None`) vira `lambda _j: None` — **todo candle é tratado como confiável**,
  comportamento "legado" explicitamente documentado no docstring da função. Já o caminho ao vivo
  passa esse callback de verdade: `grep -n "candle_confiavel=" signals_mvp/pos_runner/live.py` →
  linhas 2776, 2969, 3170, 3418 (as 3 primeiras são as atualizações de paper V1/V2/V3 ao vivo). O
  motivo de existir (`qualidade_candle.motivo_suspeito` → `candle_corrompido_provavel`) é
  precisamente vetar um candle com vol=0/variação ~100x de decidir stop/TP1/saída — exatamente o tipo
  de evento que já produziu o trade de -561R do McRib (tasks #88-89 do histórico do projeto,
  marcação retroativa manual via `scripts/marcar_contaminados.py`).
- **Impacto nas conclusões**: toda estatística de R@72h calculada por `varredura_v3.py` (que é
  literalmente a fonte dos números "ao_vivo"/"retro_lote1"/"replay_v3"/"universo_admitido" citados
  nas rodadas 9-13) roda sobre um motor (`calcular_r_horizonte`) que pode deixar um candle
  corrompido decidir um stop/TP — um outlier artificial pode estar inflando ou destruindo a média/
  mediana de R@72h sem que a tag `contaminado_candle`/`risco_irrealista` (que só existe no fluxo de
  `analise/condicional.py`, via marcação MANUAL retroativa) nunca seja aplicada a essas linhas.
  `varredura_v3.py` tem SEUS PRÓPRIOS checks de `candle_corrompido_provavel` em pontos específicos
  (linhas 195, 199, 347, 401 — ver achado seguinte), mas eles não necessariamente cobrem TODO o
  caminho interno que `calcular_r_horizonte`→`simulate_v1` percorre candle a candle até o corte de
  72h/7d.
- **Correção proposta**: `horizonte_fixo._simular_e_marcar` deveria aceitar e repassar um
  `candle_confiavel` opcional (mesma assinatura do `simulate_v1`), com os chamadores passando a MESMA
  checagem que `varredura_v3.py` já faz (`candle_corrompido_provavel`, sem precisar do cross-check
  DexPaprika que só existe ao vivo). **Isto é uma mudança de cálculo** sobre um documento com hash
  próprio (`docs/pos-runner-v1/EMENDA_2026-11-05_HORIZONTE_FIXO_PROPOSTA.md`,
  `garantir_emenda_registrada`) — pela disciplina do próprio projeto, precisa de uma emenda datada
  nova, nunca um patch silencioso no texto já registrado.
- **Toca hash/exige restart?**: não toca `ParamsV1/V2/V3` nem os 3 hashes congelados; toca o hash da
  emenda `EMENDA_2026-11-05_HORIZONTE_FIXO_PROPOSTA.md` (precisa de emenda nova). Não exige restart
  do bot ao vivo (o motor só é usado por scripts offline/análise).
- **Confiança**: alto — citação de linha direta, comportamento confirmado lendo as duas funções lado
  a lado.

### [P2] `varredura_v3.py` checa `candle_corrompido_provavel` em pontos específicos, não ao longo de todo o caminho
- **Evidência**: `signals_mvp/scripts/varredura_v3.py:195,199,347,401` chamam
  `candle_corrompido_provavel(bars, idx)` em pontos isolados (entrada, e outro ponto não totalmente
  mapeado nesta sessão por limite de tempo). Não encontrei, no tempo desta auditoria, uma trilha que
  confirme que TODO candle consumido por `calcular_r_horizonte` (chamado por este mesmo script para
  R@72h) passa por este mesmo check.
- **Impacto nas conclusões**: parcialmente redundante com o achado anterior; relevante para saber se
  o incidente McRib poderia se repetir SEM detecção manual.
- **Correção proposta**: mapear exatamente quais chamadas de `calcular_r_horizonte` em
  `varredura_v3.py` já passam por um check de corrupção ANTES, e documentar isso explicitamente (ou
  aplicar a correção do achado anterior, que resolve os dois de uma vez).
- **Toca hash/exige restart?**: não.
- **Confiança**: médio — não tive tempo de rastrear cada call site até o fim nesta sessão (ver "O que
  não foi possível verificar").

### [negativo/positivo, confiança alta] Não encontrei lookahead no detector nem no simulador
- **Evidência**: `DetectorV1.update()` (`signals_mvp/pos_runner/detector_v1.py:137-151`) é
  estritamente incremental — recebe 1 `Bar` por vez, levanta `ValueError` se `bar.ts <=
  self.bars[-1].ts` (linha 138), e toda decisão (`_check_zone`/`_update_wave`/`_gatilhos`) só lê
  `self.bars[0:i+1]`/`self.peak`/`self.peak_idx` (estado acumulado até o candle atual, nunca um
  `max()`/`min()` sobre a série completa calculado de antemão). O veto de candle suspeito
  (`detector_v1.py:188-190`) compara só com o candle ANTERIOR (`self.bars[i-1]`), nunca o seguinte —
  comentário no próprio código confirma isto como regra deliberada ("regra 'sem lookahead'").
  `simulate_v1` (`signals_mvp/pos_runner/simulate_v1.py:103-116`) usa `j0 = event.idx + 1` e
  `entry = bars[j0].open` — o preço de entrada é o OPEN do candle **seguinte** ao candle de decisão,
  nunca o close do próprio candle de sinal. O caminho de replay/retro
  (`signals_mvp/scripts/varredura_v3.py:263-264,301-302`) alimenta os MESMOS candles, 1 por vez, no
  MESMO `det.update(bar)` incremental — não há um loop vetorizado que decida com conhecimento do
  futuro. `horizonte_fixo.calcular_r_horizonte` (`signals_mvp/pos_runner/horizonte_fixo.py:100-123`)
  trunca explicitamente a série (`bars_truncados = [b for b in bars if b.ts <= ts_corte]`) **antes**
  de chamar `simulate_v1`, nunca depois.
- **Impacto nas conclusões**: este é o pior bug possível que uma auditoria deste tipo poderia achar
  (inflaria artificialmente TODO resultado reportado até agora). Não encontrei evidência dele. Isto
  não é uma prova formal de ausência (não substitui um teste dedicado de não-lookahead rodando
  contra fixtures adversariais), mas é uma leitura cuidadosa de todos os pontos de decisão críticos.
- **Confiança**: alto para o que foi lido; médio para "não existe NENHUM outro lugar" dado o tamanho
  do código e o tempo desta sessão.

### [P1] `perdido_offline` não é tratado nos scripts de análise formal (consistente com design, mas vale re-confirmar)
- **Evidência**: `grep -rn "perdido_offline" signals_mvp/analise/condicional.py signals_mvp/scripts/varredura_v3.py signals_mvp/scripts/avaliar_v3_retro.py` → **zero ocorrências**. O status só é
  escrito/lido em `live.py` (ver `signals_mvp/pos_runner/live.py:866-930`: só atribuído quando
  `pool_row is None or pool_row["status"] != "ativo"` — nunca para um pool só lento). Os scripts
  offline (`varredura_v3.py`, `horizonte_fixo.py`) recalculam R direto dos candles em `pr_bars`,
  **independente** do campo `status` do sinal ao vivo — então um sinal marcado `perdido_offline` no
  bookkeeping ao vivo ainda teria seu R@72h recalculado corretamente por esses scripts, DESDE QUE os
  candles daquele pool continuem em `pr_bars` (o que é provável, já que `pr_bars` é um cache
  write-once, nunca apagado). Isto é uma leitura POSITIVA (sem viés de sobrevivência por esta via),
  mas eu não confirmei isso rodando contra dados reais — é inferência de código, não medição.
- **Impacto nas conclusões**: se a inferência estiver certa, não há viés de sobrevivência por
  `perdido_offline` nas estatísticas exploratórias (varredura_v3/horizonte_fixo). MAS a análise
  formal H1 (`analise/condicional.py`, ver Parte C/D) usa uma fonte DIFERENTE (`pr_baseline_
  resolvidas_com_dif`, filtrada por `status="fechado"`) que **exclui** `perdido_offline` por
  construção — ver achado cruzado na Parte C/D sobre H1 nunca ter sido migrado para o motor de
  horizonte fixo.
- **Correção proposta**: nenhuma aqui — a correção real é a reconciliação H1 vs horizonte_fixo
  (documentada na Parte C deste pacote).
- **Toca hash/exige restart?**: não.
- **Confiança**: médio — inferência de código, não execução contra dado real.

### [P2] Nenhuma checagem de volume do candle de entrada vs tamanho de posição modelado
- **Evidência**: `grep -rn "posicao_pct_supply\|tamanho_posicao" signals_mvp/pos_runner/*.py` mostra
  que `posicao_pct_supply`/`tamanho_posicao_usd` são calculados a partir de `banca_inicial_usd` e do
  `supply` do token (`pos_runner_v3.py: posicao_pct_supply`), nunca comparados contra
  `bars[j0].volume` (o volume do candle de entrada). Não encontrei nenhum filtro/covariável que
  avise quando o tamanho de posição modelado excede o volume real negociado no candle de entrada.
- **Impacto nas conclusões**: um trade "vencedor" no papel pode ser fisicamente irrealizável se o
  volume do candle de entrada for pequeno demais para absorver a posição sem mover o preço — ver
  Parte E para o tratamento completo de realismo de execução; aqui só confirmo que a checagem NÃO
  existe no pipeline de dados.
- **Correção proposta**: adicionar `volume_candle_entrada` como covariável (nunca filtro, pela
  mesma disciplina de "medição, nunca decide" do resto do projeto) nas tabelas de sinal.
- **Toca hash/exige restart?**: não (seria instrumentação nova, fora do hash).
- **Confiança**: alto — busca direta, nenhuma menção encontrada.

### [P2] Detecção de clone/vamp é exclusiva de V1/V2 (V3 é deliberadamente "lean")
- **Evidência**: `grep -n "vamp_risk" signals_mvp/pos_runner/live.py` só aparece em `_entry_v1`
  (linha ~2654) e `_entry_v2` (equivalente). `_entry_v3` tem docstring explícito (linha 3056-3060):
  "MESMA estrutura de `_entry_v1`, LEAN: sem holders/authority/vamp_risk/carteiras_pro (zero chamada
  RPC extra nesta entrega -- simplificacao documentada, V3 e silenciosa/medicao)". **Isto já é uma
  simplificação DISCLOSED no próprio código**, não um bug escondido.
- **Impacto nas conclusões**: sinais V3 não têm proteção contra tokens-clone (mesmo ticker, token
  mais antigo e maior) nem a tag `holders_tag`/`mint_authority`/`freeze_authority` que V1/V2 têm —
  um sinal V3 pode estar entrando num clone sem aviso algum na linha do sinal.
- **Correção proposta**: nenhuma ação aqui além de citar — é uma decisão já tomada e documentada
  pelo operador; só reforço que ela está em vigor e afeta a qualidade dos sinais V3 especificamente.
- **Toca hash/exige restart?**: mudar isso tocaria `ParamsV3`? Não diretamente (adicionar
  instrumentação não-filtrante não mudaria o hash de `ParamsV3`, só o código de `_entry_v3`), mas é
  trabalho novo, não uma correção de bug.
- **Confiança**: alto — citação direta do docstring que já admite a simplificação.

### [verificado, confiança alta] `candle_confiavel`/qualidade de candle É aplicado de forma consistente no caminho ao vivo entre V1/V2/V3
- **Evidência**: `grep -n "candle_confiavel=" signals_mvp/pos_runner/live.py` → linhas 2776, 2969,
  3170 (as atualizações de paper de V1, V2 e V3 respectivamente) todas passam o callback.
- **Impacto nas conclusões**: positivo — o veto de candle corrompido funciona igualmente para as 3
  versões ao vivo (só o motor OFFLINE de horizonte fixo que diverge, achado P1 acima).
- **Confiança**: alto.

### [verificado, confiança alta] Mesmo `DetectorV1`/mesma disciplina incremental usada no vivo e no replay
- **Evidência**: `signals_mvp/scripts/varredura_v3.py:261-264,299-302` instancia `DetectorV1(params,
  tf, row["l_bc"], row["grad_ts"], created_ts)` e alimenta candle a candle via `det.update(bar)` —
  idêntico ao padrão em `live.py` (`_detector_v1`/`_detector_v2`/`_detector_v3`,
  `signals_mvp/pos_runner/live.py:2059,2096,2135`). Única classe de detector para as 3 versões (só
  `params` difere) — ver também Parte C, achado sobre compartilhamento de detector entre hipóteses.
- **Impacto nas conclusões**: positivo para consistência entre origens — qualquer achado do
  detector em uma versão é estruturalmente idêntico nas outras 2 (ponto que pesa bastante na Parte D/G
  sobre múltiplas comparações: um só ponto de falha testado 3x não é 3 testes independentes).
- **Confiança**: alto.

## O que NÃO foi possível verificar nesta sessão

- Qualquer número real (R@72h, contagem de tokens, latência p95 medida, taxa de 429) — não existe
  banco ao vivo neste checkout. Os achados acima são 100% sobre CÓDIGO, nunca sobre dados reais.
- fill_gaps (`signals_mvp/pos_runner/candles.py:64`) — localizei a função mas não tive tempo nesta
  sessão de ler o corpo completo e confirmar formalmente que nunca usa dado futuro nem que o candle
  preenchido é marcado de forma recuperável a jusante (`filled` existe como campo em `pr_bars`, o que
  sugere que SIM é marcado — mas não confirmei que todo consumidor downstream realmente checa esse
  campo).
- Latência p95/429/lacunas sistemáticas por horário/chain — não medido (precisa do banco ao vivo).
- Rastreamento completo de todos os call-sites de `calcular_r_horizonte` dentro de `varredura_v3.py`
  para confirmar se CADA um já tem um check de corrupção equivalente antes de chamar.
- Comparação byte a byte entre `pr3_token_next_seq` (ao vivo, por ordem de INSERÇÃO) e
  `calcular_token_signal_seq` (offline, por ordem de `t_entrada`) — estruturalmente deveriam
  coincidir sob operação normal (sem replay fora de ordem), mas não testei um caso sintético.
- DexPaprika fallback/cross-check especificamente (arquivo não lido nesta sessão por falta de tempo).
