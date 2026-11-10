# Rodada 16 — Parte D: Estatística e processo

Auditoria read-only (PAPER). Nenhum código/parâmetro/hash alterado nesta parte. Resumo: a disciplina
de correção por família (Holm/Bonferroni) está **realmente implementada em código**, não só em
texto, e verifiquei isso diretamente (`holm_bonferroni`, `analise/condicional.py:436`). A censura
MTM (pendente/sem_dado) é tratada simetricamente entre sinal e controle — também verificado no
código, não só no texto do pré-registro. O achado mais importante desta parte é P1: o projeto corre
**várias famílias de Holm paralelas, nunca combinadas numa família única projeto-inteiro** — cada
família individual está corrigida corretamente, mas a superfície de busca acumulada (todas as
famílias somadas) é grande e nenhum número único a resume. Não fiz uma varredura exaustiva de
`git blame`/`git log` para achar retunes não-declarados (ver limitações no fim).

## Inventário de hipóteses/variantes/estratos já olhados (não exaustivo — ver limitações)

| id/nome | doc de origem | unidade | n mínimo p/ reportar | família de correção | status conhecido |
|---|---|---|---|---|---|
| H1 (V1/V2) | PLANO_ANALISE_PREREGISTRADO.md §H1 | token (1ª tentativa) | 15 (futilidade) / 30 (decisão) | nenhuma (única confirmatória) | sem resultado publicado neste checkout |
| H1 (V3, cauda) | PREREGISTRO_V3_2026-11-02.md + EMENDA_2026-11-10_FUTILIDADE_CAUDA_OPCAO_A | token (1ª tentativa) | N=30/N=60 (emenda 4) | Bonferroni α/2 V1×V3 | INCONCLUSIVO esperado em N=30 (texto, MDE≈1,2-1,4R) |
| H2 (gatilho, 3 grupos) | PLANO_ANALISE_PREREGISTRADO.md §H2-H8 | sinal | 10/grupo | Holm (família H2-H12, até 16 testes) | exploratória, sem resultado publicado aqui |
| H3 (risco%) | idem | sinal | 10/grupo | Holm | idem |
| H4 (liquidez, mediana) | idem | sinal | 10/grupo | Holm | idem |
| H5 (holder concentrado) | idem | sinal | 10/grupo | Holm | idem |
| H6 (base_ge_2d) | idem | sinal | 10/grupo | Holm | idem |
| H7 (janela de ouro) | idem | sinal | 10/grupo | Holm | idem |
| H8 (carteiras_pro>=1, V1/V2) | idem §H8 | sinal | 10/grupo c/ dado não-nulo | Holm (mesma família) | nunca atingiu n>=10 até este commit (texto do próprio doc) |
| H9 (n_pessoas_pro>=2, PROPOSTA) | idem §H9 | sinal | 10/grupo | Holm | PROPOSTA, corte >=2 nunca confirmado pelo operador (texto do doc) |
| H10 (velocidade da queda, Spearman) | EMENDA 1 §2 | sinal | 10/lado | Holm (mesma família de H2-H9) | geração de hipóteses, não confirmatória |
| H11 (ticket médio, Mann-Whitney) | EMENDA 1 §2 | sinal | 10/lado | Holm | idem |
| H12 (ordem do sinal no token) | EMENDA 1 §2 | token (via bootstrap por token) | 10/lado | Holm | idem |
| H13 (tamanho_base_candles) | EMENDA 2 | sinal | não especificado explicitamente no trecho lido | fora da família H2-H12 (fonte de dados própria, `sombra:base_min4`) | geração de hipóteses |
| H14 (Radar "caixa em formação") | EMENDA 3 | alerta de estudo | não especificado no trecho lido | fora da família de Holm (fonte própria) | geração de hipóteses |
| 8 estratos V3 (16 grupos) | `analise/condicional.py:710-735` | sinal | 10/grupo | Holm (família própria, separada de H2-H12) | exploratória |
| saída fiel (variante de gestão) | PREREGISTRO_SAIDA_FIEL_2026-11-06.md | sinal | — | — (comparação descritiva, nunca decide H1) | exploratória, motivada por achado já visto (texto do próprio doc admite) |
| grade de saídas parciais (24 variantes × 3 origens = 72 testes) | PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md | sinal, por origem | — | Holm **por origem separadamente** (3 famílias independentes, nunca combinadas) | exploratória, motivada por achado já visto (B3b, texto do próprio doc admite) |
| varredura_v3 (B1-B9, múltiplas origens + estratos) | PREREGISTRO_VARREDURA_V3_2026-11-05.md | sinal/token (misto, por seção) | varia | reusa a família dos 8 estratos | exploratória |
| carteiras forward (sinal vs placebo) | PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md | token (1ª tentativa) | 20/braço | Bonferroni α/2 (sinal × placebo) | PRÉ-REGISTRADA, zero dado ainda (tabela nova) |
| PQ-V1 (native participant quality) | docs/native-participant-quality-holdout-v1-result-2026-09-24.md | — | — | — | **KILL** (fonte de dado diferente, nunca reaberta pelas hipóteses acima) |

### [P1] Múltiplas famílias de Holm/Bonferroni nunca combinadas numa família projeto-inteira
- **Evidência**: tabela acima — pelo menos 5 famílias de correção distintas e independentes já
  rodaram ou estão pré-registradas sobre o mesmo pool de sinais V1/V2/V3 (H2-H12 ≈16 testes,
  8-estratos-V3 ≈16 testes, saídas parciais 72 testes/3 famílias, carteiras forward 2 testes,
  varredura_v3 reusa a família dos estratos). `PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md:88` declara
  isso explicitamente: "3 famílias independentes, nunca uma família combinada".
- **Impacto nas conclusões**: cada família individual está corrigida corretamente (Holm/Bonferroni
  real, verificado em código — ver achado seguinte), mas a probabilidade de **pelo menos um** "achado
  candidato" aparecer em ALGUMA família ao longo de todas as rodadas é maior do que qualquer alfa
  individual sugere. Isto é esperado/aceitável para um programa de pesquisa em estágio exploratório
  (CLAUDE.md já governa isso via "discovery produces candidates, never a validated edge directly" e
  o registro de hipóteses exige 3 passos — PASS pré-registrado, replicação fresca, Gate 2 — antes de
  qualquer promoção), mas **nenhum relatório único mostra a contagem agregada de testes já corridos
  no projeto inteiro** — um operador que olhe só o resultado de uma família isolada pode subestimar
  quão grande é a busca total já feita.
- **Correção proposta**: um "ledger" único (markdown ou tabela em `meta`) que acumula TODO teste já
  corrido/pré-registrado em qualquer família, com contagem corrente — não para mudar o alfa de cada
  família (que já é tratada corretamente), mas para dar visibilidade honesta da escala total da busca.
- **Toca hash/exige restart?**: não — é só um novo documento/relatório, zero código de produção.
- **Confiança**: alto — baseado em leitura direta dos textos pré-registrados que admitem isso.

### [P2] H13/H14 não declaram explicitamente seu `n` mínimo de reporte no trecho lido
- **Evidência**: `docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md:238-323` (EMENDA 2/3) — não vi
  (no trecho que li) um `n>=10` explícito equivalente ao de H2-H12 para H13/H14.
- **Impacto nas conclusões**: se H13/H14 forem reportados com `n` pequeno sem aviso, um estrato raro
  pode parecer informativo sem ser.
- **Correção proposta**: confirmar (releitura completa das EMENDAs 2/3) se o `n` mínimo existe em
  outro trecho que não vi, e se não existir, declarar um explicitamente.
- **Toca hash/exige restart?**: não.
- **Confiança**: baixo — não li o documento completo, só a seção de títulos + H1/H2-H9/EMENDA 1; é
  bem possível que o `n` mínimo esteja declarado em uma parte que não revisei nesta passada.

## Achados verificados (fato, não hipótese)

### [FATO] Holm-Bonferroni está realmente implementado, não só descrito em texto
`signals_mvp/analise/condicional.py:436-448`: `holm_bonferroni` é o step-down clássico (ordena
p-valores, compara o i-ésimo contra `alpha/(m-rank)`, para no primeiro que falha). Usado tanto pela
família V1/V2 (H2-H12, em torno da linha 1003-1022) quanto pelos 8 estratos V3 (`_grupos_v3_estratos`,
linha 710-735, chamado por `holm_bonferroni` na linha 751). **Confiança: alto.**

### [FATO] A censura MTM (pendente/sem_dado) é simétrica entre sinal e controle
`signals_mvp/scripts/horizonte_fixo.py:102-108`: `dif_pareada` só é calculado (não fica `None`)
quando **tanto** `r.r_mult` (sinal) **quanto** `r_controle_medio` (controle) são resolvidos — se
qualquer um dos dois lados estiver `pendente`/`sem_dado`, a diferença fica `None` e é excluída de
AMBOS os lados do bootstrap (`analise/condicional.py:237`: `if row["dif_pareada"] is not None`).
Isto é exatamente o que os pré-registros declaram ("nunca um corte que favoreça um lado") — e eu
verifiquei isso no código, não só no texto. **Confiança: alto.**

### [FATO] `calcular_r_horizonte` é causal (bars truncados ANTES de simular, nunca depois)
`signals_mvp/pos_runner/horizonte_fixo.py:106-116`: `bars_truncados = [b for b in bars if b.ts <=
ts_corte]` acontece **antes** de chamar `_simular_e_marcar` — a simulação nunca vê um candle além do
corte do horizonte. Isto é o oposto de lookahead (ver também Parte B/C para o resto do pipeline).
**Confiança: alto.**

## "O que já foi visto julgando a si mesmo" — casos declarados abertamente

- `EMENDA_2026-11-10_FUTILIDADE_CAUDA_OPCAO_A.md` declara explicitamente ser motivada por 3
  disclosures já vistos (05/11, 06/11, retrospectivo 10/11) e lista exatamente quais dados **não**
  podem julgar a nova regra (os 10 vencidos ao vivo + todo `retro_lote1`/`replay_v3` já replayado).
- `PREREGISTRO_SAIDA_FIEL_2026-11-06.md` e `PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md` ambos
  declaram abertamente serem motivados por achados já vistos (B3b da rodada 11/13).
- Isto é a forma CORRETA de lidar com o problema — declarar a motivação, nunca escondê-la, e exigir
  coleta nova sob o hash novo antes de julgar.

### [P1] Não auditei `git log`/`git blame` em busca de retunes NÃO declarados
- **Evidência**: nenhuma — esta é uma lacuna de cobertura, não um achado positivo.
- **Impacto nas conclusões**: se existir algum parâmetro que foi ajustado silenciosamente após ver um
  resultado ruim (sem abrir uma emenda formal), eu não o encontrei nesta passada — não porque não
  exista, mas porque não fiz a varredura histórica necessária (exigiria `git log -p` sobre
  `params_v1.py`/`params_v3.py`/`PLANO_ANALISE_PREREGISTRADO.md` cruzado com as datas de cada rodada,
  trabalho que não cabe no tempo desta parte).
- **Correção proposta**: uma rodada futura dedicada a isso, com `git log --follow -p` nos arquivos de
  parâmetros e pré-registros, comparando datas de commit de PARÂMETRO contra datas de commit de
  RESULTADO/ANÁLISE.
- **Toca hash/exige restart?**: não.
- **Confiança**: alto na honestidade da lacuna (sei que não fiz a varredura); zero conclusão sobre se
  existe ou não o problema em si.

## Unidades (token vs sinal)

Confirmado: H1 (V1/V2 e V3) e H12 declaram explicitamente "token" (1ª tentativa/`token_signal_seq`)
como unidade; H2-H11 e os 8 estratos V3 usam "sinal" (cada ENTRADA conta, incluindo reentradas) como
unidade — e os próprios documentos rotulam isso corretamente onde eu li. Não encontrei, no texto que
revisei, um lugar que misture as duas sem avisar — mas esta não é uma varredura exaustiva de TODO
output de TODO script (ex.: `varredura_v3.py` tem uma função dedicada,
`resumo_r72h_por_ordem_sinal`, exatamente para não misturar — isso é evidência A FAVOR da disciplina
correta, citada no próprio nome da função, rodada 10 item 2).

## Vazamento retro/replay vs forward

`docs/pos-runner-v1/EMENDA_2026-11-02_COORTE_RETROSPECTIVA.md:8,32` confirma: a coorte retrospectiva
é CONGELADA (`congelado_em`) antes de qualquer execução de análise rodar sobre ela, e "toda execução
seguinte lê de volta esta mesma lista, nunca recalcula". Isto é o padrão correto — **fato
verificado** a partir do texto do próprio documento de congelamento (não verifiquei a tabela real no
banco, que não existe neste checkout — ver limitações).

## Poder estatístico — resumo (reuso, não recálculo)

- V3, N=30, R pareado: MDE ≈ 1,21R sem correção / 1,37R com Bonferroni α/2
  (`EMENDA_2026-11-05_PODER_ESTATISTICO_N30.md`, DP≈2,68R do bootstrap `retro_lote1` n=25).
- Carteiras forward (2 amostras, n=20/braço mínimo declarado): MDE ≈ 2,11R sem correção / 2,37R com
  Bonferroni α/2 (`PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md`, mesmo DP reusado).
- **Leitura honesta**: os dois MDEs são grandes comparados à magnitude típica de R por trade (~1R) —
  ambos os próprios documentos já admitem que `INCONCLUSIVO` é o resultado esperado por bastante
  tempo. Não encontrei, na minha leitura, nenhum estrato com `n<10` sendo reportado como se decidisse
  algo (a regra `n<10 nunca é reportado` parece aplicada consistentemente nos trechos que li).

### [P2] Dois DPs diferentes (2,68R) usados para desenhos de poder DIFERENTES, sem re-medição
- **Evidência**: ambos MDEs acima reusam o MESMO DP≈2,68R, medido originalmente sobre
  `retro_lote1`/n=25 para a H1 pareada da V3 — mas aplicado também ao desenho de poder das carteiras
  forward, que é uma pergunta DIFERENTE (comparação entre dois grupos de tokens, não pareamento
  sinal-controle). Isto é dito abertamente nos dois documentos ("nunca um valor novo inventado"),
  então não é um erro escondido — mas a variância REAL da comparação de carteiras forward pode ser
  diferente da variância do pareamento V1 original.
- **Impacto nas conclusões**: os MDEs de carteiras forward podem estar levemente errados (pra qualquer
  direção) porque usam um proxy de variância de outro desenho — mas isso já é reconhecido como "a
  única fonte de dispersão disponível hoje" nos dois casos, nunca escondido.
- **Correção proposta**: quando houver dado real de carteiras forward suficiente, remedir o DP
  específico desse desenho em vez de continuar reusando o V1 original.
- **Toca hash/exige restart?**: não.
- **Confiança**: médio.

## Contradições entre docs e código

Não encontrei, com alta confiança, nenhuma contradição clara entre um pré-registro congelado por hash
e o código atual — todo pré-registro que tem um `garantir_X_registrada`/hash-lock (saída fiel,
carteiras forward, horizonte fixo, plano de análise) é mecanicamente impedido de divergir silenciosamente
do texto registrado (o hash-lock recusa com erro se o texto mudar sem reabrir uma emenda). O risco
real não é "o texto mudou sem avisar" (isso está mecanicamente bloqueado) — é "o CÓDIGO que implementa
o texto tem um bug sutil que não bate com a intenção do texto", o que é território da Parte B/C, não
desta parte.

## O que NÃO foi possível verificar nesta sessão

- Não há banco ao vivo da VM neste checkout — não verifiquei nenhuma contagem REAL de `n` por grupo,
  só a LÓGICA que calcularia esses números.
- Não fiz `git log`/`git blame` histórico em busca de retunes não-declarados (ver achado P1 acima).
- Não li o texto completo de todas as EMENDAs 2/3/4 do plano V1/V2, nem o texto completo de
  `PREREGISTRO_VARREDURA_V3_2026-11-05.md`/`PREREGISTRO_SAIDAS_PARCIAIS_2026-11-10.md` — só os
  trechos relevantes para os itens pedidos. Pode haver detalhes de correção/família que não capturei.
- Não contei o número exato de testes em `varredura_v3.py` (B1-B9) — a tabela acima trata isso como
  "reusa a família dos estratos" por inferência do código, não por leitura linha a linha de todas as
  seções B1-B9.
