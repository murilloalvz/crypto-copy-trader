# Emenda 2026-11-05 — item 2 (promoção de cadência para runner/pullback/trajetória aberta) e item 3 (capacidade 45 pools)

PEDIDO 2026-11-05 (dados da VM: latência de candle p95~58min, tier morno p50~41min, 1
entrada_atrasada em 24h; 21 pools em runner/pullback; RSS 1,9MB/pool). PAPER/READ-ONLY. **Não altera
detector, simulate, parâmetros ou critério de sinal** (`ParamsV1=279b79ffa3f0`,
`ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6` intactos) — item 2 é só infraestrutura de polling
(AMOSTRAGEM: decide QUANDO um poll acontece, nunca detecção/entrada/saída/banca), item 3 é só
confirmação de capacidade (nenhum código).

## Item 2 — promoção de cadência (`live.py: _heat`)

**Causa raiz da latência**: `_heat()` já tratava posição aberta/pullback como quente (heat=0, 1ª
passada de `tick()`, NUNCA throttled pelo teto suave de ~20/min) — mas fase **RUNNER** sempre virava
heat=1 ("morno"), que na prática faz o `_interval` ficar IGUAL ao de quente no tf 1h (3600s), só que
o pool concorre na **2ª passada** (`rank>0`, junto com descoberta e frio/sem-carga, sob o teto suave).
Pior: `_heat()` só olhava V0/V1 — um pool em runner/pullback/trajetória aberta **só na V2 ou só na
V3** nunca pesava na cadência (gap pré-existente, nunca corrigido antes desta emenda). É isso que
produz os 41-58min de latência reportados: o pool espera atrás da fila throttled em vez de ser
atendido no topo da hora como já acontece com posição aberta/pullback.

**Correção** (`POS_RUNNER_CADENCIA_QUENTE`, padrão LIGADO): fase RUNNER passa a contar como quente
(heat=0) em V0/V1/V2/V3 (antes só V0/V1 eram olhados); trajetória ainda aberta
(`pr_trajetoria_pool_tf_aberta`, `fechado=0` — a janela de medição de 72h pode continuar rodando
mesmo depois que a posição/sinal já fechou) também conta como quente. `POS_RUNNER_CADENCIA_QUENTE=0`
desliga tudo isso de uma vez (volta ao `_heat` de antes: só V0/V1, RUNNER=morno, trajetória sem peso
extra) — interruptor único, sem precisar reverter o commit.

**Respeita o teto suave de ~20/min**: a mudança NUNCA toca `MAX_CHAMADAS_POR_MIN_PADRAO`/
`_orcamento_disponivel_este_minuto` (só a 2ª passada usa esse teto, intocado) nem `_schedule`/
`_interval` (intervalo do tf 1h continua 3600s para heat 0 e 1, igual a antes) — só MOVE os pools
promovidos da 2ª passada (throttled) para a 1ª (prioridade absoluta, mesma categoria de posição
aberta/pullback hoje).

**Estimativa de efeito**:
- **chamadas/h**: o VOLUME total não muda (cada pool no tf 1h continua precisando de ~1 poll/hora,
  antes e depois) — o que muda é A ORDEM dentro do ciclo: os ~21 pools saem da fila throttled
  (2ª passada, competindo com descoberta+frio/sem-carga) e entram na 1ª passada (mesma prioridade de
  posição aberta, nunca throttled). Nenhuma chamada NOVA é criada por esta emenda.
- **p50/p95 esperados**: o tier promovido deveria cair para a MESMA ordem de grandeza que posição
  aberta já tem hoje (atendida na 1ª passada, LAG_S=90s de folga após o fechamento do candle) — ou
  seja, de ~41-58min para a faixa de minutos (não segundos, por causa de LAG_S + fila da 1ª passada
  quando várias posições abrem no mesmo ciclo), nunca mais perto de 1h. **Número exato precisa vir da
  VM** (comandos abaixo) comparando o `funil_diario.py`/`saude.py` ANTES e DEPOIS do restart.
- **429**: risco não deveria SUBIR (nenhuma chamada nova, mesmo teto suave na 2ª passada) — se
  alguma coisa muda, é a 2ª passada (descoberta+frio/sem-carga) ficar com MAIS fatia do teto de
  ~20/min disponível, já que menos pools competem ali agora (efeito colateral positivo, não
  garantido, a confirmar com `pr_api_uso_rate_limited_count_desde`).

## Item 3 — capacidade com `POS_RUNNER_MAX_POOLS=45`

Com RSS atual medido na VM de **1,9MB/pool**: 45 pools ≈ **85,5MB** de RSS atribuível a pools — bem
dentro da margem de 200MB de folga já usada como referência (`funil_diario.py: FOLGA_RSS_KB`) em
rodadas anteriores (mesmo dobrando por segurança, 171MB, ainda cabe). O orçamento de chamadas (item
2) não piora isso: a promoção de cadência não aumenta o VOLUME de chamadas, só a prioridade — logo
45 pools com a promoção ligada não deveria estressar o teto suave de ~20/min mais do que 45 pools
sem a promoção estressariam hoje. **Seguro para subir.**

## Testes e hashes

28 testes novos/atualizados (`test_pos_runner_v1_live.py`: +3 nova classe `CadenciaQuenteTests`;
`test_storage_evidencia.py`: +1; `test_pos_runner_live.py`: 1 teste pré-existente ajustado —
`test_failed_discovery_list_does_not_stop_the_refreshes` testava resiliência a falha de descoberta,
não prioridade de agendamento, e precisou da promoção desligada via env para manter sua asserção
original). Suíte completa: ver resposta final. Hashes `ParamsV1=279b79ffa3f0`/
`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6` intactos.

## Comandos na VM (a partir da raiz do repo, posições abertas V1=0/V2=0 — seguro reiniciar agora)

```
git pull origin signals-mvp

# adicionar ao .env na raiz do projeto (python-dotenv ja carrega esse arquivo no startup):
echo "POS_RUNNER_MAX_POOLS=45" >> .env
# POS_RUNNER_CADENCIA_QUENTE=1 e o padrao -- so adicionar se quiser deixar explicito:
echo "POS_RUNNER_CADENCIA_QUENTE=1" >> .env

# RESTART NECESSARIO (mudanca de codigo ao vivo: _heat/_schedule).
sudo systemctl restart <nome-do-servico-systemd-do-bot>

# depois do restart, medir o ANTES/DEPOIS real (compara com p95~58min/p50~41min reportados):
python -m signals_mvp.scripts.funil_diario --db signals_mvp/dados/estado.sqlite
python -m signals_mvp.scripts.saude --db signals_mvp/dados/estado.sqlite

# pra desligar a promocao de cadencia (reverte so o item 2, sem tocar max_pools):
echo "POS_RUNNER_CADENCIA_QUENTE=0" >> .env && sudo systemctl restart <nome-do-servico-systemd-do-bot>
```
