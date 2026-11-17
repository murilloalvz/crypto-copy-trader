# Emenda 2026-11-16/17 — correção do owner + exclusão de pool/curva em `pr_carteiras_snapshot`/`pr3_carteiras_sinal`

PAPER/READ-ONLY. `ParamsV1=279b79ffa3f0`/`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6` ficam
INTOCADOS. Esta emenda é sobre a **captura** (instrumentação de carteiras "pro"), nunca sobre
detector/sinal/critério. Documento NOVO e SEPARADO — nunca edita
`docs/pos-runner-v3/PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md` em si (isso quebraria o hash
congelado por `carteiras_forward.garantir_carteiras_forward_registrada`, chamado 1x no startup —
editar o texto original faria a VM recusar subir com `PreregistroAlteradoError`). Esta emenda
**complementa** aquele pré-registro; as seções 1–7 dele continuam valendo integralmente.

## 1) O bug (achado na Rodada 20, pergunta 3; corrigido na Rodada 21)

`chain_adapter.SolanaAdapter.holders()` resolvia o "owner" de cada top-holder lendo
`getAccountInfo(...).value.owner` — esse campo é, para **qualquer** token account real, sempre o
Program ID que gerencia a conta (SPL Token Program, `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA`),
nunca a wallet que de fato detém os tokens (essa fica em `value.data.parsed.info.owner`). Confirmado
ao vivo contra `api.mainnet-beta.solana.com` e pelo método vizinho `authorities()`, que já fazia o
unwrap correto.

Como `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA` já está em `BASE_EXCLUDED_PROGRAMS`, o owner lido
errado batia **sempre** no conjunto excluído — `owners`/`top_holders` ficava **sempre vazio** e
`top_pct` **sempre 0.0** em qualquer chamada real. Consequência direta: **toda** linha gravada em
`pr_carteiras_snapshot` e em `pr3_carteiras_sinal` desde que essas tabelas existem (rodada 15, Parte
2/3) tem `n_carteiras_pro`/`n_pessoas_pro` artificialmente travado em **0**, mesmo quando uma
carteira "pro" de fato estava entre os top holders. Isto não é ruído/amostra pequena — é um viés
estrutural (sempre na mesma direção, sempre a mesma magnitude) em **100%** das linhas capturadas
antes desta correção.

## 2) Correção (Rodada 21, 2026-11-16)

`chain_adapter.SolanaAdapter.holders_com_owner()` (função NOVA — `holders()` fica byte a byte
intocada, ver `test_holders_nunca_foi_alterado_por_holders_com_owner`) lê o owner correto
(`value.data.parsed.info.owner`), via `getMultipleAccounts` em lotes de até 5 contas
(`enumerate.GET_MULTIPLE_ACCOUNTS_BATCH` — QuickNode no plano "discover" free já recusava mais que
isso por chamada, HTTP 413, medido em produção 2026-10-16/17; nunca reintroduzido). Usada **só**
pela instrumentação de carteiras forward (`_atualizar_carteiras_horaria`, snapshot de ENTRADA V1/V2,
`_capturar_carteiras_sinal_v3_holders`) — nunca por tags/`holders_tag`/`HOLDER_CONCENTRADO`/
`carteiras_pro_presentes` em `pr1_signals`/`pr2_signals` (ver §5 abaixo, fora do escopo desta
emenda).

Invariante de sanidade nova: se o RPC responde mas **nenhum** owner válido sobra (tudo
excluído/sem_owner) ou a soma de `pct` resolvida é 0, a linha nunca fica `cobertura_valida=1` por
omissão — vira `holders_indisponivel`/`erro_classe='owner_nao_resolvido'` (nunca confundida com
falha de transporte). Alarme correspondente em `saude.py`
(`LIMIAR_OWNER_NAO_RESOLVIDO=5`, backstop lido direto do banco).

Marcador de versão do coletor: toda linha NOVA de `pr_carteiras_snapshot`/`pr3_carteiras_sinal`
grava `coletor_versao='owner_fix_v1_2026-11-16'` (`chain_adapter.CARTEIRAS_COLETOR_VERSAO`), junto
com `contas_totais`/`contas_excluidas_pool_curva`/`contas_sem_owner` (cobertura real do top-20, ver
§4 da Rodada 20). Colunas adicionadas via `_ensure_columns` (idempotente); linhas antigas ficam com
`coletor_versao IS NULL`.

## 3) Corte de amostra — ZERO ESTRUTURAL, nunca um dado perdido

**Dados antigos NUNCA são editados nem apagados** (git rules do `CLAUDE.md` raiz: nunca reescrever
histórico científico já queimado). Em vez disso, esta emenda declara formalmente, para QUALQUER
análise presente ou futura sobre `pr3_carteiras_sinal`/`pr_carteiras_snapshot` (incluindo a hipótese
exploratória do `PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md`, §2/§5):

> **Toda linha com `coletor_versao IS NULL` (gravada antes do deploy desta correção) conta como
> ZERO ESTRUTURAL — nunca entra em nenhuma contagem de N (os 20/20 por braço exigidos no §5 do
> pré-registro), nunca entra em nenhuma média/delta/IC, nunca é lida como "0 carteiras pro"
> (que seria um valor observado) — é dado AUSENTE por defeito de coleta, categoria diferente de
> `cobertura_valida=0` (que já era tratado como ausente). A contagem de N do pré-registro
> recomeça do zero na data do deploy desta correção na VM real, usando só linhas com
> `coletor_versao='owner_fix_v1_2026-11-16'` (ou versão mais nova, se houver).**

Isto segue a mesma disciplina do `CLAUDE.md` raiz: "a systems failure before the economic gate does
not spend an attempt" — este bug é uma falha de sistemas (leitura de campo errada), nunca um
resultado econômico; as linhas antigas nunca "gastaram" uma tentativa da hipótese, porque nunca
mediram o que diziam medir.

**Nenhuma linha antiga precisa ser apagada** para isso — o filtro `coletor_versao IS NOT NULL` (ou
`= 'owner_fix_v1_2026-11-16'`) no script de análise (ainda não implementado, per §"O que este
pré-registro NÃO faz" do documento original) é suficiente e preserva o histórico completo para
auditoria.

## 4) Itens da Rodada 20, pergunta 1 e 2 (achados relacionados, registrados aqui)

Dois achados adicionais da revisão de 2026-11-13/15, sobre a MESMA instrumentação de carteiras
forward, relevantes para quem for ler `pr3_carteiras_sinal`/o relatório de `saude.py`:

- **(pergunta 1) Déficit de placebo nunca registrado**: `PosRunnerLive._carteiras_pools_controle`
  (`live.py`) pode devolver menos que K candidatos (poucos pools na mesma fase/tf sem posição
  aberta) e `_capturar_carteiras_sinal_v3` pula silenciosamente um pool-controle sem `mint`
  conhecido — nenhum dos dois casos grava contador/motivo. Um `signal_id` com menos de K linhas
  `tipo='placebo'` não tem, hoje, como se distinguir "déficit de candidatos elegíveis" de "pool sem
  mint" só pelos dados já gravados. **Não corrigido na Rodada 21** (fora do escopo "owner") —
  a REGRA de leitura (não a instrumentação de captura) é declarada na Rodada 22, §6(a) abaixo.
- **(pergunta 2) "Cobertura" do placebo em `saude.py` media a fração errada**: a linha
  `forward V3: ... placebo=N (cobertura=M)` em `_secao_carteiras` era `M/N` — fração de linhas
  **existentes** com `cobertura_valida=1`, nunca fração de linhas **esperadas** (`K × n_sinais`).
  Um déficit do item acima (menos linhas que o esperado) nunca aparecia nessa métrica — ela só media
  a qualidade das linhas que de fato existem. **Corrigido na Rodada 22, §6(a) abaixo**
  (`cobertura_deficit = coletados/(K × n_sinais)`, exibida ao lado da cobertura_valida antiga, nunca
  substituindo-a).

## 5) Fora do escopo desta emenda (achado, não decidido aqui)

`pr1_signals.carteiras_pro_presentes`/`n_pessoas_pro` e `pr2_signals.carteiras_pro_presentes`/
`n_pessoas_pro` (gravados por `_entry_v1`/`_entry_v2`, hipótese pré-registrada **H8** —
`docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md`, "`carteiras_pro_presentes >= 1`") usam a MESMA
lista de owners de `holders()` (nunca `holders_com_owner()`, que fica reservada à instrumentação
"carteiras forward" desta emenda) — ou seja, **o mesmo bug afeta H8**: `carteiras_pro_presentes` tem
sido `0` para todo sinal V1/V2 desde que o campo existe (2026-10-27), independente de haver ou não
uma carteira "pro" real entre os top holders. H8 "segue fora do Holm até n>=10 por grupo" (ainda não
testada formalmente) — mas qualquer N já acumulado sob o bug está na mesma situação do §3 acima
(zero estrutural, nunca um "0" observado real).

**Esta emenda não corrige H8** — mexer em `_entry_v1`/`_entry_v2`/`holders()` para isso exige uma
decisão própria do operador (é um contrato de pré-registro diferente, com sua própria disciplina de
N/Holm) e está fora do pedido desta rodada ("correção do owner em carteiras"). Fica registrado aqui
para que o operador decida, numa rodada futura e com uma emenda própria ao `PLANO_ANALISE_
PREREGISTRADO.md`, se/como corrigir H8 e como tratar o N já acumulado sob o bug (mesma lógica de
corte "zero estrutural" do §3 provavelmente se aplica, mas isso é uma decisão nova, não automática).

## 6) RODADA 22 (2026-11-17, autorizada) — exclusão de pool/curva (owner_fix_v2) + 4 itens da análise

### 6.0) Achado que motivou esta rodada

Com o owner correto (Rodada 21) rodando numa VM, 19 snapshots novos foram observados:
`contas_excluidas_pool_curva=0` em **todos** os 19, e em **12 de 19** o 1º holder resolvido era o
**próprio endereço do pool** (coluna `pool`). Causa: `excluded_accounts()` só excluía o PROGRAMA do
launchpad/AMM destino (compartilhado por todos os pools daquele launchpad), nunca a conta
ESPECÍFICA deste pool — que é quem de fato custodia o supply enquanto é o maior "holder" (o vault
do próprio AMM, ou a bonding-curve antes da migração).

### 6.1) Correção (item 1 do pedido) — `owner_fix_v2`

`chain_adapter.excluded_accounts_carteiras_forward()` (função NOVA — `excluded_accounts()` em si
fica intocada, continua alimentando `holders()`/tags/HOLDER_CONCENTRADO/H8, nunca tocados) reusa
`excluded_accounts()` e adiciona:
- o próprio `pool` (endereço já conhecido, só não era usado — o parâmetro existia na assinatura
  desde a Rodada 15 sem nunca ser lido);
- quando `launchpad=='pumpfun'`: o PDA da bonding-curve do mint (seeds=`['bonding-curve', mint]`,
  programa pump.fun `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`), via `solana_pda.
  find_program_address` (módulo novo, só stdlib — `create_program_address`/`find_program_address`
  EXATAMENTE como o runtime do Solana especifica, checagem de ponto Ed25519 válido inclusa).

**Validação do algoritmo de PDA** (nunca só um vetor de teste memorizado): computada a Associated
Token Account (seeds=`[wallet, Token Program, mint]`, programa `ATokenGPvbdGVxr1b2hvZbsiqW5xWH25
efTNsLJA8knL`) para um par (wallet, mint) observado AO VIVO nesta sessão via `getTokenAccountsByOwner`
contra `api.mainnet-beta.solana.com` — o endereço computado bateu exatamente com o endereço real
on-chain.

**Seed da bonding-curve — CONFIRMADO contra dado real (condição 1 do operador, Rodada 22)**: ao
contrário da ressalva original desta emenda (que dizia "nunca confirmado ao vivo"), esta rodada
localizou 4 transações reais recentes que referenciam o programa pump.fun
(`getTransaction`/`jsonParsed` contra `api.mainnet-beta.solana.com`, filtrando contas cujo endereço
termina em "pump" — sufixo vanity característico dos mints do pump.fun — e testando se o endereço
computado aparece na MESMA lista de contas da instrução/CPI) e testou `['bonding-curve', mint]`
contra os 4 pares (mint, bonding-curve) resultantes — **os 4 bateram exatamente**, incluindo 1 par
Token-2022 (`create_v2`), o que também testa e descarta a hipótese de precisar de
`'bonding-curve-v2'` nesse caso. Fixture completa (mints/endereços reais) em
`test_solana_pda.BondingCurveSeedFixtureTests` — inclui um teste que confirma que `'bonding-curve-v2'`
**não** bate com nenhum dos 4 pares reais, descartando a hipótese por completo (nunca só por
omissão). `raydium_launchlab`/`meteora_dbc` não têm PDA de curva implementado aqui (só pump.fun foi
pesquisado/confirmado) — ficam cobertos só pela exclusão de programa já existente. Backstop
permanente em `saude.py`: alarme se `contas_excluidas_pool_curva=0` em todos os últimos
`MINIMO_SNAPSHOTS_PARA_ALARME_POOL_CURVA=5` snapshots do coletor v2+ (cobre o caso de o pump.fun
mudar o seed de novo no futuro, sem depender de outra sessão revisitar isto manualmente).

`CARTEIRAS_COLETOR_VERSAO` sobe para `'owner_fix_v2_2026-11-17'` **imediatamente** (antes de
qualquer sinal V3 real ser capturado sob a v1 — condição do operador para subir agora em vez de
esperar). Linhas gravadas sob `'owner_fix_v1_2026-11-16'` **nunca são apagadas/editadas** — ficam
como **diagnóstico** (prova de que o owner já estava certo, só a exclusão de pool/curva que
faltava) e, pela MESMA lógica do §3 acima, **fora de qualquer contagem de N** do pré-registro —
só linhas `coletor_versao='owner_fix_v2_2026-11-17'` (ou versão mais nova) contam daqui em diante.

### 6.2) Itens da análise (item 2 do pedido)

**(a) Mínimo de placebo por sinal + cobertura real em `saude.py`.**
Proposta (nunca decidida sozinha — pede aceite do operador): um sinal V3 real precisa de **pelo
menos 1 linha `tipo='placebo'` com `cobertura_valida=1`** para entrar no braço placebo da seção 4
do pré-registro original. Um sinal com **zero** placebo válido (déficit de candidatos elegíveis —
pergunta 1 da Rodada 20 — ou todos os candidatos com `cobertura_valida=0`) recebe o rótulo
`sem_comparador` **na hora da ANÁLISE** (quando o script de §"O que este pré-registro NÃO faz" for
escrito) — esse sinal **sai do braço placebo** (nunca entra no delta do placebo, nunca é contado
no denominador do teste de confundimento §4 do pré-registro), mas **continua no braço sinal**
(sua própria leitura de R@72h/`n_carteiras_pro` nunca depende de ter comparador). Justificativa do
mínimo=1 (nunca 0, nunca >1): zero placebo não permite calcular NENHUMA média de comparação; exigir
mais que 1 (ex. todos os K) descartaria sinais só por um déficit parcial de candidatos, reduzindo a
amostra do braço sinal sem necessidade (o braço sinal não depende do placebo). Isto é uma regra de
**leitura/análise** (não existe script de análise ainda — ver "O que este pré-registro NÃO faz" do
documento original) — não precisa de código nesta rodada, só da definição aqui.

A métrica de cobertura em `saude.py` (`_secao_carteiras`) agora mostra **as duas**, lado a lado:
`cobertura_valida` (fração das linhas EXISTENTES com holders resolvidos — métrica antiga, mede
qualidade) e `cobertura_deficit` (`coletados/(K × n_sinais)`, usando `carteiras_placebo_k` gravado
em `pr_carteiras_runtime` desde esta rodada — métrica nova, mede o déficit da pergunta 1 da Rodada
20). Nenhuma das duas decide a hipótese — só diagnóstico, igual ao resto do painel.

**(b) Pareamento também por idade do pool e porte (volume/mcap) — só dados futuros.**
`PosRunnerLive._carteiras_pools_controle` agora também exige, quando a covariável do PRÓPRIO
pool-gatilho é conhecida: idade (`grad_ts`) dentro de ±50% da idade do gatilho, e volume 24h
(`info.vol_h24_usd`, já cacheado — zero chamada de rede nova) dentro de 0,1×–10× do volume do
gatilho. Reverte a simplificação do pré-registro original (§2: "casar idade/MC exigiria recalcular
covariáveis... custo que só o placebo não justifica") porque idade/volume já estão cacheados em
`pr_pools` — o custo que motivou a simplificação não existe mais para essas duas covariáveis (MC/
preço em si continua fora, exigiria uma cotação SOL/USD fresca por candidato). Se a covariável do
candidato for desconhecida enquanto a do gatilho é conhecida, o candidato é EXCLUÍDO (fail-closed);
se a do PRÓPRIO gatilho é desconhecida, a dimensão correspondente é ignorada (nunca rejeita tudo só
por falta de dado do gatilho). **Nunca re-pareia linhas já gravadas** — afeta só a seleção de
candidatos daqui em diante. Faixas (±50% idade, 0,1×–10× volume) são escolhas documentadas, não
otimizadas — o operador pode pedir ajuste (`live.PLACEBO_FAIXA_IDADE_FRAC`/
`PLACEBO_FAIXA_VOLUME_MULT`).

**(c) Desfecho secundário robusto, declarado.**
Adicionado à seção "6) Secundário (diagnóstico, nunca decide sozinho)" do pré-registro original
(nunca a substitui, nunca entra na família de correção Bonferroni — mesma regra já escrita lá para
`n_pessoas_pro`/`pct_supply`): **P(+2R antes de −1R)**, usando a MESMA convenção de toque causal já
usada pela hipótese "entrada no suporte" (`entrada_suporte.toque_causal`/`garantir_suporte_forward_
registrada`) — comparado entre o braço `>=1 pro` e `0 pro`, e entre sinal e placebo (mesma lógica
RED-COHORT do §4). Reportado também em **leave-token-out**: a mesma estatística recalculada
excluindo o(s) token(s) de maior magnitude de R (mesma convenção já usada na Rodada 18, item 2,
"leave-token-out (sem PEAK/HIGH) lado a lado com a passada completa") — robustez contra 1-2 tokens
dominarem o resultado numa amostra ainda pequena, nunca uma segunda tentativa de "achar edge" se a
primeira não aparecer.

**(d) Regra de inviabilidade por prevalência — redefinida por token, com IC de Wilson (condição 3
do operador, Rodada 22).**

A versão original desta proposta (ainda nesta rodada, antes do aceite condicional do operador)
media prevalência **por snapshot** (linha de `pr_carteiras_snapshot`) — o operador pediu a correção:
um mesmo token pode gerar vários snapshots horários (uma vez por hora enquanto elegível), então
contar por snapshot pesa mais os tokens que ficam elegíveis por mais tempo, inflando ou subestimando
a prevalência real dependendo de QUAIS tokens duram mais. A unidade correta é o **token**.

> Definição: **prevalência = (nº de tokens distintos com `n_carteiras_pro>=1` em PELO MENOS UM
> snapshot horário válido) / (nº de tokens distintos com PELO MENOS UM snapshot horário válido)**,
> restrito a `coletor_versao>='owner_fix_v2_2026-11-17'` (owner correto + exclusão de pool/curva —
> nunca linhas antigas, §3/§6.1, zero estrutural). `pr_carteiras_snapshot.mint` já identifica o
> token (nunca o `pool`, que pode mudar entre pré/pós-migração — mesma disciplina de identidade por
> `mint` já usada no resto do projeto, Rodada 17 item 2).

> Regra: se, **X = 14 dias corridos** após o deploy desta correção, o **limite SUPERIOR do IC de
> Wilson (95%)** sobre essa prevalência ficar **abaixo de Y = 15%**, a coleta do
> `PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md` via sinais V3 é declarada **INVIÁVEL NO RITMO
> ATUAL** — nunca `FAIL` da hipótese em si (que continua aberta, só sem prazo de resolução,
> exatamente como o pré-registro original já previa na seção 5). Usar o limite SUPERIOR (nunca a
> prevalência pontual) é deliberadamente conservador: só declara inviável quando o dado exclui,
> com 95% de confiança, que a prevalência real possa estar em 15% ou mais — nunca uma decisão
> precipitada sobre um ponto estimado ruidoso em amostra ainda pequena. `wilson_ci` (`pos_runner/
> estatistica.py`, módulo novo, só stdlib) implementa o score interval de Wilson — mais honesto que
> o normal/Wald em n pequeno ou p perto de 0 (nunca produz um intervalo de largura 0, nunca um
> limite fora de `[0,1]`).

Justificativa de X/Y (poder, nunca otimizado — proposta para aceite):
- **Por que medir pela coleta HORÁRIA (não pelos sinais V3)**: a V3 é "silenciosa/rara" (1 sinal
  real por vez, mais K placebos — §5 do pré-registro original) — esperar N=20/20 sinais reais só
  para descobrir que a prevalência de base é baixa poderia levar muitos meses. A coleta horária
  (todo pool elegível, toda hora) acumula uma amostra de TOKENS DISTINTOS muito maior muito mais
  rápido, sobre a MESMA população de wallets/pools — serve de alerta precoce.
- **Por que Y=15%**: para o braço sinal (§2 do pré-registro) chegar a n=20 no grupo minoritário
  (`>=1 pro`) por acaso puro, o número esperado de sinais V3 totais necessários é aproximadamente
  `20 / p` (p = prevalência real, por token — ver §6.2d-estimativa abaixo, condição 4 do operador).
  Com p=15%, isso é ~133 sinais; com a V3 rara, 133 sinais poderia levar bem mais de um ano — já no
  limite do "impraticável". Um Y menor (ex. 5%) exigiria ~400 sinais (pior ainda); um Y maior (ex.
  30%) declararia inviável um cenário que na verdade teria uma chance razoável de resolver em
  meses — 15% é o ponto onde a conclusão "impraticável no ritmo atual" já é defensável sem ser
  desnecessariamente pessimista.
- **Por que X=14 dias**: poder para DISTINGUIR "prevalência real < 15%" de "prevalência real >=
  15%" precisa de um número de TOKENS DISTINTOS (nunca snapshots) que dê um IC de Wilson com
  largura útil. Com p≈5-10% (prevalência baixa típica esperada) e n≈50-100 tokens distintos
  observados, o IC de Wilson já fica com largura da ordem de poucos pontos percentuais — útil o
  bastante para o limite superior ficar abaixo de 15% quando a prevalência real é de fato baixa.
  Quantos tokens DISTINTOS passam pela coleta horária elegível em 14 dias depende da taxa de
  chegada de pools elegíveis (não medida nesta sessão, sem acesso ao banco real) — 14 dias é uma
  janela plausível dado o universo de pools elegíveis já observado em rodadas anteriores (~20+),
  mas o operador deve tratar X como um PRIMEIRO corte, ajustável se o `n` de tokens acumulado em 14
  dias ficar visivelmente baixo (poucas dezenas) — o próprio IC de Wilson já torna isso visível (IC
  largo = ainda sem poder de decisão, continuar esperando, nunca forçar uma conclusão).

**(d-estimativa) Tempo estimado até N=20 no grupo `>=1 pro` (condição 4 do operador).**

> `tempo_estimado_dias = 20 / (prevalência × sinais_por_dia)`

onde `prevalência` é a mesma definida acima (por token, Wilson) e `sinais_por_dia` é a taxa
observada de sinais V3 reais (`pr3_signals`, evento=ENTRADA) por dia corrido. **Esta sessão não tem
acesso ao banco real da VM e não pode preencher a faixa de `sinais_por_dia` observada** — o
operador deve computar `(nº de sinais V3 em `pr3_signals`) / (dias corridos entre o 1º e o último
`ts_fechamento`)` (ideal: também reportar separadamente a taxa dos últimos 7/14 dias, já que a
taxa pode não ser estável — mesma disciplina de "ETA só dos últimos 3 dias" já usada em
`funil_diario.py`). Exemplo ilustrativo (números fictícios, só para mostrar a fórmula): se
`sinais_por_dia` observado estiver entre 0,3 e 1,0 (uma faixa plausível dado "V3 é silenciosa/rara",
nunca medida de verdade aqui) e a prevalência ficar em 15%, `tempo_estimado_dias` ficaria entre
`20/(0,15×1,0)≈133` e `20/(0,15×0,3)≈444` dias — a faixa real só pode vir do banco da VM.

Nenhum destes 4 itens (a-d) tem código de captura novo nesta rodada **exceto** (a)'s métrica de
`saude.py` e (b)'s pareamento em `_carteiras_pools_controle` (já implementados, ver testes) — (a)'s
regra de `sem_comparador`, (c) e (d)/(d-estimativa) são regras de ANÁLISE, declaradas para quando o
script de análise (ainda não escrito) for implementado; `wilson_ci` (`pos_runner/estatistica.py`)
já existe e está testado, pronto para esse script usar.

## O que esta emenda NÃO faz

- Não altera detector, simulador, parâmetros (`ParamsV1`/`ParamsV2`/`ParamsV3`) nem seus hashes.
- Não altera nenhuma seção do `PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md` original (texto
  congelado por hash, intocado).
- Não corrige H8 (`pr1_signals`/`pr2_signals.carteiras_pro_presentes`) — ver §5, decisão própria do
  operador.
- Não registra o déficit de placebo na CAPTURA (pergunta 1 da Rodada 20 continua sem contador/
  motivo gravado) — só declara a regra de LEITURA (`sem_comparador`, §6.2a) para quando o script de
  análise existir.
- Não implementa PDA de bonding-curve para `raydium_launchlab`/`meteora_dbc` (só pump.fun foi
  pesquisado/confirmado contra dado real — §6.1).
- Não implementa o script de análise (deltas/IC/placebo/P(+2R antes de -1R)/regra de
  inviabilidade) — continua ausente, mesma declaração do pré-registro original.
- Não apaga nem edita nenhuma linha histórica de `pr_carteiras_snapshot`/`pr3_carteiras_sinal`
  (nem as da v1, nem as anteriores).
- Não entra em produção nesta sessão — as mudanças de código só valem no próximo restart que o
  operador fizer, depois de revisar o diff.

## Status

**Registrada em 2026-11-16, emendada em 2026-11-17 (Rodada 22, §6).** Complementa
`PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md` (que permanece a autoridade formal para unidade/
amostra/teste/poder estatístico — seções 1–7 dele, inalteradas). Esta emenda não tem hash próprio
travado por `garantir_*_registrada` (não há coleta condicionada a ela — ela só documenta um corte
de amostra e aponta pro marcador `coletor_versao` já gravado em cada linha, que é a fonte de
verdade objetiva). Os itens (a)-(d) do §6.2 (mínimo de placebo/`sem_comparador`, pareamento idade/
porte, desfecho secundário P(+2R antes de -1R)/leave-token-out, regra de inviabilidade X=14
dias/Y=15%) **aguardam aceite explícito do operador** antes de serem tratados como regras
definitivas da análise futura.
