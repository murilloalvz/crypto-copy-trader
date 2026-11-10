# Rodada 17, item 6 — direção do viés do H1 ao excluir 'aberto'/'perdido_offline' + rascunho de emenda

PEDIDO 2026-11-10 (autorizado, Rodada 17, item 6). **TEXTO APENAS — nenhum código, parâmetro,
detector ou hash de `ParamsV1`/`ParamsV2`/`ParamsV3` (`279b79ffa3f0`/`d57b4331d51d`/`56762db29cd6`)
é tocado.** Este documento (a) cita o mecanismo exato (com linha de código) pelo qual o H1 de V1/V2
hoje exclui sinais `aberto`/`perdido_offline`, (b) dá a direção do viés resultante com a melhor
evidência quantitativa já existente no repositório, (c) declara a limitação desta sessão (sem acesso
ao banco real da VM — mesma limitação já documentada em `docs/revisao-2026-11-10/PARTE_A_
VERIFICACAO_NUMEROS.md`) e dá o comando exato para o operador medir o número real, e (d) deixa um
**rascunho de emenda datada** (não implementada) propondo migrar o H1 para o motor de horizonte
fixo — item explicitamente pedido como "declarar que é motivada por achados já vistos", nunca uma
emenda "a frio".

## 1) O mecanismo exato (código, não suposição)

`analise/condicional.py: carregar_sinais_e_excluidos` (linha 232) usa, por padrão
(`horizonte=None`), `storage.pr_baseline_resolvidas_com_dif(versao)` como fonte de `dif_pareada` — e
essa função (`storage.py:1990-1992`) filtra literalmente `WHERE dif_pareada IS NOT NULL`.

`dif_pareada` só é escrito em `live.py: _atualizar_baseline` (linha ~3475) sob esta condição exata:

```python
if signal["status"] == "fechado" and signal["result_net"] is not None and risco_pct_sinal:
    r_sinal = 100.0 * signal["result_net"] / risco_pct_sinal
```

Um sinal com `status in ("aberto", "perdido_offline", "cancelado", "descontinuado")` **nunca** passa
por este `if` → `r_sinal` fica `None` → `dif_pareada` fica `None` → a linha de `pr_baseline` nunca
tem `dif_pareada IS NOT NULL` → o sinal **nunca** entra na amostra que decide H1 (futilidade, N=30,
critérios a-d). Isto é exatamente o comportamento que o pedido quer quantificar.

A chamada que decide o relatório de H1 que o operador vê (`analise/condicional.py:1054`,
`sinais, excluidos = carregar_sinais_e_excluidos(storage, versao)`) **não passa `horizonte=`** —
continua no modo legado (`fechado-apenas`), mesmo depois da emenda de 2026-11-05 (seção 2) ter
introduzido e autorizado a alternativa.

## 2) Isto já foi encontrado e corrigido — só nunca ligado por padrão

`docs/pos-runner-v1/EMENDA_2026-11-05_HORIZONTE_FIXO_PROPOSTA.md` já nomeia este EXATO mecanismo como
**censura** e já foi **autorizada e implementada** como infraestrutura (`horizonte_fixo.py`,
`pr_horizonte_fixo`, o parâmetro `horizonte="72h"/"7d"` em `carregar_sinais_e_excluidos`) — citação
literal do próprio texto da emenda:

> "`carregar_sinais_e_excluidos` ... exige `signal["status"] == "fechado"` ... Perdedores fecham
> rápido (stop bate cedo) e entram logo na amostra; vencedores demoram e são excluídos enquanto
> correm — a amostra de qualquer corte no tempo é **desproporcionalmente perdedora**."

Ou seja: a **direção do viés já está declarada, por escrito, desde 05/11** — fechado-apenas
subestima o desempenho real (viés NEGATIVO), porque exclui vencedores que ainda estão correndo
enquanto conta perdedores que já estouraram o stop. O que nunca aconteceu foi religar o relatório de
H1 (item 1 acima) para usar `horizonte="72h"` por padrão — a emenda ficou implementada mas não
adotada como default. Isto por si só é um achado da Rodada 17: uma correção já autorizada, com texto
congelado por hash, que nunca chegou a ser ligada no caminho que o operador realmente lê.

## 3) Magnitude já quantificada (a melhor evidência disponível, nunca uma suposição nova)

A mesma emenda cita o número que motivou a correção, calculado no `exit_lab` sobre o replay V3:

> "viés de censura: A passa de **-1,11R para -0,31R** no replay V3 ao valorizar a mercado os trades
> ainda `em_aberto`"

Isto é a variante de saída A do `exit_lab` (não é literalmente o `dif_pareada` do H1 de V1/V2, mas é
o **mesmo mecanismo de censura**, já medido uma vez): fechado-apenas mostra -1,11R; horizonte-fixo
MTM mostra -0,31R — uma diferença de **+0,80R**, na direção que a seção 2 prevê (fechado-apenas
subestima). Esta sessão **não pode** recalcular isto separado por V1 vs V2 nem confirmar se a mesma
magnitude se repete no `dif_pareada` real de H1 — ver limitação na seção 4.

## 4) Limitação desta sessão (declarada sem rodeio, mesma lógica da Parte A da Rodada 16)

Este checkout (sessão cloud isolada) **não tem acesso ao banco SQLite ao vivo da VM** (`.gitignore`
exclui `*.sqlite`/`*.db`, confirmado em `docs/revisao-2026-11-10/PARTE_A_VERIFICACAO_NUMEROS.md`).
Por isso, a comparação pedida — `dif_pareada` médio fechado-apenas vs horizonte-fixo MTM, **separada
por versão (V1 e V2)** — não pode ser recalculada aqui com dado real.

**Comando exato para o operador medir isto na VM** (read-only, reusa `carregar_sinais_resolvidos` já
existente — nenhuma lógica nova):

```bash
# 1) garantir que pr_horizonte_fixo esta populado para v1/v2 (se ainda nao estiver)
python -m signals_mvp.scripts.horizonte_fixo --db dados/estado.sqlite --versao v1
python -m signals_mvp.scripts.horizonte_fixo --db dados/estado.sqlite --versao v2

# 2) comparar fechado-apenas vs horizonte-fixo MTM, por versao
python3 -c "
import statistics
from signals_mvp.config import make_paths
from signals_mvp.storage import Storage
from signals_mvp.analise.condicional import carregar_sinais_resolvidos

storage = Storage(make_paths())
for versao in ('v1', 'v2'):
    fechado = carregar_sinais_resolvidos(storage, versao, horizonte=None)
    mtm_72h = carregar_sinais_resolvidos(storage, versao, horizonte='72h')
    def resumo(sinais):
        if not sinais:
            return 'n=0'
        vals = [s.dif_pareada for s in sinais]
        return f'n={len(vals)} media={statistics.fmean(vals):+.3f}R mediana={statistics.median(vals):+.3f}R'
    print(f'{versao} fechado-apenas:  {resumo(fechado)}')
    print(f'{versao} horizonte 72h:   {resumo(mtm_72h)}')
storage.close()
"
```

PASS/FAIL não se aplica aqui (não há número-alvo citado pelo pedido para esta comparação) — a saída
acima é o número em si, pronta para colar neste documento quando rodada na VM.

## 5) Rascunho de emenda datada (NÃO IMPLEMENTADA) — migrar o H1 ao motor de horizonte fixo

**Rascunho, 2026-11-10 — texto apenas, nunca registrado por hash nesta rodada** (registro por hash
só acontece quando o operador autorizar explicitamente a implementação, mesma disciplina de
`garantir_plano_registrado`/`garantir_emenda_registrada` já em uso no projeto).

**Declaração explícita (pedido do operador): isto não é uma emenda "a frio".** É motivada
diretamente pelos achados já vistos:

- `EMENDA_2026-11-05_HORIZONTE_FIXO_PROPOSTA.md` — já nomeou a censura, já autorizou e implementou a
  infraestrutura (`horizonte_fixo.py`), mas nunca ligou o relatório de H1 a ela por padrão (achado
  da seção 2 deste documento).
- Retrospectivo não-condicionado da saída fiel (Rodada 12/13) — já comparou saída-fiel vs saída-atual
  sobre os MESMOS sinais reais `ao_vivo`/`retro_lote1`/`replay_v3`, familiarizando o projeto com a
  ideia de reportar duas medidas lado a lado em vez de uma só.
- Achado P1 da Rodada 16 (`PARTE_A_VERIFICACAO_NUMEROS.md`): números citados em conversa/rodada sem
  trilha de auditoria commitada — exatamente o tipo de buraco que religar o default sem pré-registro
  explícito poderia repetir, por isso este rascunho fica só rascunho até ser formalmente autorizado.

**Mudança proposta** (quando/se autorizada, em rodada futura): `analise/condicional.py` linha 1054
(e qualquer outra chamada de `carregar_sinais_e_excluidos(storage, versao)` sem `horizonte=` que
alimente o relatório de H1 lido pelo operador) passa a usar `horizonte="72h"` como fonte PRIMÁRIA de
`dif_pareada` para V1 e V2 — exatamente a mesma troca que `EMENDA_2026-11-05_HORIZONTE_FIXO_
PROPOSTA.md` já desenhou e autorizou como mecanismo (`rodar_h1` fica byte a byte intocada; só a fonte
de `dif_pareada` muda, atrás do parâmetro que já existe). O `dif_pareada` fechado-apenas (legado)
continua reportado lado a lado, rotulado explicitamente como **censurado** — nunca removido do
relatório, só deixa de ser o desfecho que decide.

**O que este rascunho NÃO faz:**
- Não altera código, detector, parâmetros ou hashes nesta rodada — é texto apenas.
- Não decide a direção do N=30/N=60 já acumulado sob o regime fechado-apenas — uma mudança de default
  no meio de uma coleta já em andamento exigiria sua própria decisão explícita do operador sobre o
  que fazer com a amostra já vista (mesma disciplina de "o que já foi visto nunca pode julgar a si
  mesmo", `research-hypothesis-registry-v1-2026-10-04.md`).
- Não promove nem invalida nenhum resultado de H1 já obtido.
- Não é registrada por hash nesta rodada — fica como proposta até o operador autorizar explicitamente
  a implementação numa rodada futura.

## Resumo (≤5 linhas para o resumo final da rodada)

Direção do viés: fechado-apenas **subestima** o desempenho real (exclui vencedores ainda correndo,
conta perdedores que já estouraram o stop) — já declarado por escrito na emenda de 05/11, magnitude
já medida uma vez no `exit_lab` (-1,11R → -0,31R, +0,80R). O religamento do relatório de H1 pra usar
isso por padrão nunca aconteceu — achado desta rodada. Esta sessão não tem banco real pra confirmar o
número separado por V1/V2; comando exato de medição dado na seção 4. Rascunho de emenda na seção 5,
não implementado.
