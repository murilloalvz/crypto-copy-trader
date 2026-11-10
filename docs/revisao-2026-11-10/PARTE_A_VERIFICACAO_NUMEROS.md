# Parte A — Verificação independente dos números-chave (Rodada 16)

PAPER/READ-ONLY. Nenhum código/parâmetro/hash tocado (`279b79ffa3f0`/`d57b4331d51d`/`56762db29cd6`
reconfirmados intactos — ver `python -c` no final deste documento). Esta parte tentou recalcular do
banco (nunca copiar de docs) os números-chave citados no pedido da Rodada 16. **O resultado mais
importante desta parte é negativo e precisa ser dito sem rodeio**: não foi possível, e por quê.

## Limitação crítica (declare primeiro, antes de qualquer número)

Este checkout (sessão cloud isolada) **não tem acesso ao banco SQLite ao vivo da VM**. Confirmado:

```
$ cat .gitignore | grep -i -E "db|sqlite"
*.sqlite
*.sqlite3
*.db
```

O único banco real commitado neste repositório é `signals_mvp/dados/pos_runner_parte_a/parte_a.sqlite`
(checkpoint explícito do harness da Parte A/V0, pré-V1/V2/V3):

```
$ python3 -c "import sqlite3; con=sqlite3.connect('signals_mvp/dados/pos_runner_parte_a/parte_a.sqlite'); \
  [print(t, con.execute(f'select count(*) from {t}').fetchone()[0]) for t in \
  [r[0] for r in con.execute(\"select name from sqlite_master where type='table'\").fetchall()]]"
meta 6
windows 1200
graduations 27349
stage1 0
stage2 0
setups 0
trades 0
```

`stage1`/`stage2`/`setups`/`trades` estão **vazios** — zero trade real neste checkout. Os bancos
`pr1_signals`/`pr2_signals`/`pr3_signals`/`pr_retro_candidatos`/`pr_bars` que alimentam `ao_vivo`,
`retro_lote1`, `replay_v3` e `universo_admitido` existem **apenas na VM do operador**, nunca foram
commitados (propositalmente — é o estado operacional real, não um fixture) e esta sessão não tem rede
para alcançar a VM.

**Consequência**: nenhum dos números pedidos (R@72h de V1/ao_vivo/retro_lote1/replay_v3, P(+NR antes
de −1R) e equilíbrio, distância do topo anterior, mediana, nº de tokens distintos, contagem de sinais
vs tokens, vencedores/em_aberto/perdido_offline) pôde ser **recalculado a partir de dado real** nesta
sessão. Isto não é uma substituição por "copiar de docs" (proibido pelo pedido) — é a declaração
explícita de que a verificação independente dos valores numéricos propriamente ditos **não é possível
aqui**, e seria enganoso fingir o contrário.

### Os números citados no pedido não aparecem em NENHUM documento commitado

Busca exaustiva (`grep -rn` em todo `docs/`) por "mediana" + "-1,1R"/"1.1R", e pela frase "distância do
topo anterior" como valor numérico, não encontrou o número "mediana −1,1R" em nenhum arquivo do
repositório. As únicas ocorrências de "mediana" relevantes são menções estruturais (ex.
`PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md:82`, `EMENDA_2026-11-04_FRENTE_A_MFE_RETRO_CORRECAO.md:29`
— ambas descrevendo que a métrica *existe*, nunca publicando o valor "-1,1R" em si).

**Achado**: ver `P1-A1` abaixo — isto é, por si só, um achado sobre disciplina de evidência, não só
uma limitação desta sessão.

## Achados

### [P1] Números operacionais citados em conversas não têm trilha de auditoria commitada
- **Evidência**: `grep -rn "mediana" docs/*.md docs/*/*.md` não retorna o valor "-1,1R"/"1.1R" em
  nenhum lugar; `grep -rln "1,1R\|1\.1R\|mediana" docs/pos-runner-v3/ docs/pos-runner-v1/` só acha
  menções estruturais à métrica, nunca o valor publicado.
- **Impacto nas conclusões**: números citados oralmente/em chat entre rodadas (mediana de R, distância
  do topo) não podem ser auditados por ninguém depois — nem pelo operador, nem por uma revisão futura
  — porque nunca foram persistidos em um artefato versionado (doc, CSV ou saída de script commitada).
  Isso é exatamente o tipo de buraco que esta Rodada 16 foi pedida para achar.
- **Correção proposta**: todo número que vira "fato citado" numa decisão (futilidade, EDGE_PROVISORIO,
  mudança de prioridade) deveria ser a saída literal de um script read-only rodado contra o banco real,
  com a saída colada num doc commitado (mesmo que informal) — nunca só reportado em prosa no chat.
- **Toca hash/exige restart?**: não.
- **Confiança**: alto — busca exaustiva, resultado negativo reproduzível por qualquer pessoa com
  `grep -rn` neste repositório.

### [P1] `varredura_v3.py` nunca usa o mint real — "token" é na verdade o SYMBOL em todas as 3 origens
- **Evidência**: `signals_mvp/scripts/varredura_v3.py:237` — `_montar_sinal(bars, ev, dex, l_bc,
  "universo_admitido", lp["symbol"], "", lp["pool"], ...)` — o 6º argumento positional (`token`) recebe
  `lp["symbol"]`, e o 7º (`mint`) recebe `""` (string vazia). Mesmo padrão em `:267-268`
  (`universo_nunca_admitido`, `row["symbol"] or row["pool"][:8]`, `""`) e `:305-307` (`retro_lote1`,
  idêntico). Dentro de `_montar_sinal` (`:205-206`): `SinalVarredura(token=token, mint=mint or
  token, ...)` — como `mint=""` é falsy, `mint or token` sempre resolve para o SYMBOL. Confirmado
  também que a query de origem (`avaliar_v3_retro.py:58-59`, `parte_a_pools_admitidos`) nem seleciona
  a coluna `pr_pools.mint` — o endereço real nunca chega a ser carregado nestas 3 origens.
  `calcular_token_signal_seq` (`varredura_v3.py:583-585`) agrupa por `s.token` — ou seja, por SYMBOL.
- **Impacto nas conclusões**: qualquer "token distinto"/"reentrada" calculado por este script
  (`universo_admitido`, `universo_nunca_admitido`, `retro_lote1` — as 3 origens que alimentam os
  estratos B3/Holm, o pareamento de controles e os números de poder/MDE já publicados) conflaria DOIS
  tokens reais diferentes que compartilham o mesmo ticker (clones/"vamp" — risco que o próprio projeto
  já trata explicitamente no path ao vivo, `INTERPRETACOES.md #4`/`vamp_risk`) como se fossem o MESMO
  token, tratando a 2ª entrada como "reentrada" em vez de um token novo, e subcontando "número de
  tokens distintos". Tickers repetidos (CAT, PEPE, ELON, DOGE...) são comuns no universo pump.fun —
  este não é um cenário de borda raro.
- **Correção proposta**: adicionar `mint` ao `SELECT` em `parte_a_pools_admitidos` (`avaliar_v3_retro.
  py:58-59`) e nos 2 outros SELECTs de `varredura_v3.py` (linhas próximas a `:256`/`:292`), e passar
  `row["mint"]`/`lp["mint"]` como o argumento `mint` real em vez de `""`, usando `mint` (nunca
  `token`/symbol) como chave em `calcular_token_signal_seq` e em qualquer contagem de "tokens
  distintos". Mudança pequena, isolada a este script exploratório — não toca detector/params/hash.
- **Toca hash/exige restart?**: não — é um script offline, fora do caminho ao vivo.
- **Confiança**: alto — citação de linha exata, comportamento confirmado por leitura direta (não
  precisei executar nada: a string vazia `""` e o fallback `mint or token` são inequívocos em texto).

### [P1] `funil_diario.py` nunca inclui a V3 — o ETA para N=30 reportado ao operador é só V1/V2
- **Evidência**: `grep -n "pr3_\|pr1_\|pr2_" signals_mvp/scripts/funil_diario.py` não retorna NENHUMA
  ocorrência de `pr3_` no arquivo inteiro. `montar_funil` (`:81-108`) usa só `pr1_signals UNION
  pr2_signals` para as etapas "sinal"/"fechado". `eta_dias_30_fechados` (`:228`, a métrica citada no
  próprio nome do pedido como "ETA em dias at 30 tokens distintos") também só conta `pr1_signals`/
  `pr2_signals` (linhas `:232-233`, `:258-259`, `:358-359`).
- **Impacto nas conclusões**: o relatório que o operador roda para acompanhar o progresso rumo aos
  pontos de olhada formais N=30/N=60 da **H1 da V3** (a hipótese de cauda, atualmente a prioridade
  declarada do projeto — `EMENDA_2026-11-10_FUTILIDADE_CAUDA_OPCAO_A.md`) não mede progresso da V3 —
  mede V1/V2. Qualquer leitura do ETA/funil feita olhando este script dá uma falsa sensação de
  progresso (ou atraso) em relação à hipótese que mais importa agora.
- **Correção proposta**: estender `montar_funil`/`eta_dias_30_fechados`/as 3 outras queries citadas
  para fazer `UNION` com `pr3_signals` (ou, melhor, parametrizar por versão e reportar as 3 colunas
  separadas — V1/V2 já são reportadas somadas, o que também mistura 2 hipóteses diferentes num só
  número; ver achado relacionado na Parte D sobre unidades/múltiplas comparações).
- **Toca hash/exige restart?**: não — script de relatório offline, read-only.
- **Confiança**: alto — grep exaustivo sem nenhum resultado, reproduzível por qualquer pessoa.

### [P2] Teste de RECALL (B9, exemplos Aoin/Solana Cat/Apil) não pode ser executado — CSV nunca preenchido
- **Evidência**: `signals_mvp/scripts/exemplos_v3_modelo.csv` contém só a linha placeholder
  (`PLACEHOLDER_preencha_com_symbol_ou_endereco_do_pool,2026-01-01T00:00:00Z,...`). `grep -rln
  "Aoin\|Apil\|exemplos_professor" .` (todo o repositório, extensões .md/.csv/.py) não retorna
  nenhuma ocorrência — os 3 exemplos nomeados pelo operador na Rodada 11 (B9) nunca foram
  transcritos para um CSV real em nenhum commit.
- **Impacto nas conclusões**: o teste de RECALL pedido na Parte C desta rodada não pôde ser executado
  por mim nem (aparentemente) em nenhuma rodada anterior — o script (`testar_exemplos_v3.py`) está
  pronto e funcional desde a Rodada 11, mas nunca recebeu os dados reais que o tornariam útil.
- **Correção proposta** (ação do operador, não do agente — o script é explícito: "NUNCA inventa
  caso"): preencher um CSV com `token_ou_pool,inicio,fim,esperado,nota` para Aoin (esperado=sinal) e
  Solana Cat/Apil (esperado=descartar), commitar, e rodar `python -m signals_mvp.scripts.
  testar_exemplos_v3 --db <banco-da-vm> --exemplos <arquivo>` na VM (onde `pr_bars`/`pr_pools`
  existem de verdade).
- **Toca hash/exige restart?**: não.
- **Confiança**: alto — ausência confirmada por grep exaustivo, não é uma suposição.

## Verificação que FOI possível: `horizonte_fixo.calcular_r_horizonte` é causal (fato verificado)

Apesar de não haver dado real para recalcular números, a **fórmula** central de R@72h/MTM usada por
`ao_vivo`/`retro_lote1`/`replay_v3`/`universo_admitido` (todos chamam a mesma função) foi lida linha a
linha (`signals_mvp/pos_runner/horizonte_fixo.py:97-123`):

- `ts_corte = t_entrada + horizonte_s`; se `now < ts_corte` → `'pendente'` (nunca decide antes do
  horizonte decorrer — linha `:107-108`).
- `bars_truncados = [b for b in bars if b.ts <= ts_corte]` (`:109`) — a série é **truncada antes** de
  chamar `simulate_v1`, nunca simulada sobre a série completa e cortada depois. Isto é a definição
  correta de "sem lookahead" para este cálculo específico.
- Pendente/sem_dado tratados como `None`/status explícito, nunca promovidos a um R=0 ou R negativo
  fabricado.

**Confiança: alto** nesta sub-verificação específica (a fórmula central é sólida); isto NÃO substitui a
verificação dos NÚMEROS reportados, que depende de dados que não existem aqui — ver limitação acima.
A Parte B (fork paralelo desta rodada) aprofunda lookahead em outros pontos do pipeline (detector,
pareamento de controles, `_exhaustion`).

## Como o operador pode obter a verificação real (comando read-only, na VM)

Os 3 scripts abaixo já são read-only e, rodados contra o banco real da VM, reproduzem exatamente os
números que este pedido queria ver recalculados — nenhum deles precisa de rede nem escreve no banco:

```bash
# funil/ETA (ainda sem V3 -- ver achado P1 acima)
python -m signals_mvp.scripts.funil_diario --db <caminho-do-banco>

# varredura V3 (universo_admitido/nunca_admitido/retro_lote1, R@72h, equilibrio, estratos)
# ATENCAO ao achado P1 de mint/symbol acima antes de confiar no "tokens distintos" deste script
python -m signals_mvp.scripts.varredura_v3 --db <caminho-do-banco> --min-ram-mb 400

# saude geral (vencedores/em_aberto/perdido_offline, posicoes abertas por versao)
python -m signals_mvp.scripts.saude --db <caminho-do-banco> --logs <dir-de-logs>
```

Recomenda-se, para uma Rodada 17 focada só nisso: exportar (ou montar read-only) uma cópia do SQLite
da VM para uma sessão com acesso a ele — o banco em si não contém segredos (tokens/pools/candles
públicos; o `TELEGRAM_BOT_TOKEN` vive em variável de ambiente, nunca no banco, confirmado em
`signals_mvp/CLAUDE.md`: "nunca logar ou commitar TELEGRAM_BOT_TOKEN").

## Hashes reconfirmados (nenhum tocado)

```
$ python -c "from signals_mvp.pos_runner.params_v1 import load_params_v1; \
  from signals_mvp.pos_runner.params_v2 import load_params_v2; \
  from signals_mvp.pos_runner.params_v3 import load_params_v3; \
  print(load_params_v1().version, load_params_v2().version, load_params_v3().version)"
279b79ffa3f0 d57b4331d51d 56762db29cd6
```

## O que NÃO foi possível verificar nesta sessão

- Qualquer valor numérico real (R médio/mediano, P(+NR), distância do topo, contagens) de
  `ao_vivo`/`retro_lote1`/`replay_v3`/`universo_admitido` — requer o banco da VM, inacessível aqui.
  Nenhuma afirmação sobre esses números "reproduz" ou "não reproduz" pode ser feita com confiança
  nesta sessão — só a ausência de trilha de auditoria para eles (achado P1-A1) e um bug de identidade
  de token que os afetaria SE recalculados hoje sem correção (achado P1-A2).
- O teste de RECALL B9 (Aoin/Solana Cat/Apil) — dado nunca fornecido.
- Qualquer verificação que dependa de medir latência/429/RAM reais da VM.
