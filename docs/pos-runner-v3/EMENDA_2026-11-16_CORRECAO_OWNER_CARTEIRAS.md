# Emenda 2026-11-16 — correção do owner em `pr_carteiras_snapshot`/`pr3_carteiras_sinal`

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
  mint" só pelos dados já gravados. **Não corrigido nesta rodada** (fora do escopo "owner") — fica
  registrado para uma rodada futura que queira instrumentar isso explicitamente.
- **(pergunta 2) "Cobertura" do placebo em `saude.py` mede a fração errada**: a linha
  `forward V3: ... placebo=N (cobertura=M)` em `_secao_carteiras` é `M/N` — fração de linhas
  **existentes** com `cobertura_valida=1`, nunca fração de linhas **esperadas** (`K × n_sinais`).
  Um déficit do item acima (menos linhas que o esperado) nunca aparece nessa métrica — ela só mede
  a qualidade das linhas que de fato existem. **Não corrigido nesta rodada** (mesma razão acima).

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

## O que esta emenda NÃO faz

- Não altera detector, simulador, parâmetros (`ParamsV1`/`ParamsV2`/`ParamsV3`) nem seus hashes.
- Não altera nenhuma seção do `PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md` original (texto
  congelado por hash, intocado).
- Não corrige H8 (`pr1_signals`/`pr2_signals.carteiras_pro_presentes`) — ver §5, decisão própria do
  operador.
- Não corrige o déficit de placebo nem a métrica de cobertura de `saude.py` (§4) — só os registra.
- Não apaga nem edita nenhuma linha histórica de `pr_carteiras_snapshot`/`pr3_carteiras_sinal`.
- Não entra em produção nesta sessão — as mudanças de código só valem no próximo restart do
  operador na VM real.

## Status

**Registrada em 2026-11-16.** Complementa `PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md` (que
permanece a autoridade formal para unidade/amostra/teste/poder estatístico — seções 1–7 dele,
inalteradas). Esta emenda não tem hash próprio travado por `garantir_*_registrada` (não há coleta
condicionada a ela — ela só documenta um corte de amostra e aponta pro marcador `coletor_versao` já
gravado em cada linha, que é a fonte de verdade objetiva).
