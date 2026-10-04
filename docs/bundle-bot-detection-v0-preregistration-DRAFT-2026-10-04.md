# Bundle Bot Detection V0 — pré-registro (RASCUNHO) — 2026-10-04

Status: **DRAFT. Não autoriza nada.** Escrito sem olhar nenhum dado (Fase A / A6). Precisa de sign-off explícito do operador e de um commit de freeze antes de qualquer coleta ou leitura de dado.

Evidência de origem: E11 em `docs/research-evidence-registry-v1-2026-09-02.md` (arXiv 2601.08641, WWW'26) para a definição; item 2 de `docs/external-evidence-reuse-map-v1.md` (RED-COHORT-2026-v1) para o controle placebo obrigatório.

## 1. Por que existe

O repositório não tem nenhum primitivo de coordenação de wallets que dispense um link direto de funding (confirmado: `src/market_integrity.py` lista `counterparty_graph_unavailable` e `funding_relationships_unavailable` como limites, e `H_ORGANIC_VS_COORDINATED_V0` não está pronto como seletor). O v61 exige transferência direta deployer→participante. Bundle detection cobre o caso em que essa transferência não existe ou não é visível.

## 2. Definição (binária, sem threshold ajustável)

`bundle_flag = 1` se pelo menos uma wallet diferente do criador comprou o token **no mesmo slot** da criação do token; senão `0`.

- Criador: o campo `creator` do evento de criação do Pump.fun.
- Slot de criação: o slot da notificação de log que contém o evento de criação.
- Só compras com `chain_time` e `observed_at` anteriores ao `decision_as_of` do episódio contam.
- Ser binário evita escolher um corte a partir dos dados. Uma versão contínua (fração do notional das primeiras compras que caiu no slot de criação) fica para uma V1 separada.

## 3. Bloqueio de observabilidade (passo 0, antes de tudo)

Hoje a definição acima **não é calculável** com o que o repositório persiste:

- `src/pump_bonding_stream.py` decodifica `slot` (em `PumpLogNotification`) e `creator` (em `PumpCreateEvent`), mas nenhum dos dois chega ao armazenamento: `MarketTradeObservation` (`src/market_opportunity_radar.py`) guarda `chain_time` em segundos, sem slot, e `MarketLifecycleObservation` não guarda o criador.
- Usar `chain_time` em segundos como substituto **não é equivalente**: um segundo cobre dois a três slots do Solana, então "mesmo segundo da criação" mistura bundle (mesmo slot) com sniper (primeiros blocos). Esse substituto não é permitido nesta V0.

Passo 0, portanto: persistir slot por trade e `creator` + slot de criação por token, com `observed_at` causal e sem backfill de dado antigo. É a mesma mudança de encanamento prevista na Fase D para o `creator` (que também destrava o v61), e precisa ficar fora da linhagem congelada do V68 ("same episode semantics").

## 4. Pergunta e direção (fixadas agora)

Hipótese de **rejeição**, não de alpha: episódios com `bundle_flag = 1` têm resultado route-only pior no horizonte de 900s do que episódios comparáveis sem bundle.

A direção vem de evidência externa, não de dado do projeto: relatos de praticante e pesquisa sobre extração por snipers no lançamento (E12, item 10 do reuse map) e contas coordenadas como marcador de risco. Se o resultado sair na direção oposta, isso é FAIL, não uma hipótese nova pronta para uso.

## 5. Controles obrigatórios desde a primeira passada

A comparação ingênua (bundle vs. sem bundle) é proibida como resultado principal, porque compra no slot de criação pode ser só sinal de popularidade.

- **Placebo pareado por atividade (principal):** cada episódio com bundle é pareado a episódios sem bundle com atividade inicial parecida, medida em janelas que não incluem o slot de criação: número de compradores únicos não-criadores e notional comprado nos primeiros 60s após a criação, mesmo venue, mesma faixa de horário UTC. O efeito só conta se aparecer contra esse grupo pareado.
- **Placebo de slot deslocado:** o mesmo cálculo usando "comprou no slot de criação + 3" no lugar do slot de criação. Se esse placebo mostrar efeito parecido, o efeito não é de bundle, é de compra muito cedo.
- Reportar a cobertura: fração dos episódios em que o slot de criação e o criador eram conhecidos causalmente. Episódios sem cobertura ficam como `UNKNOWN`, nunca como `0`.

## 6. Discovery e depois confirmação

- Discovery V0: amostra prospectiva nova, coletada depois do passo 0. Saída: contagem de episódios por grupo, cobertura, e o contraste contra os dois placebos, com os mesmos números do Gate 3 (`docs/live-readiness-gates-v1.md`).
- Resultado possível da discovery: `ITERATE` (merece confirmação) ou `KILL`. Discovery nunca gera PASS.
- Confirmação: pré-registro novo, amostra nova, mesmas regras congeladas.

Parâmetros para o operador congelar no sign-off: tamanho mínimo da amostra de discovery (proposta: 40 episódios com bundle pareados), número de pares por episódio (proposta: 3) e o critério numérico de ITERATE (proposta: diferença de mediana de 900s contra o placebo de atividade de pelo menos 15 pontos percentuais, com a mesma direção nas duas metades da amostra).

## 7. Proibido

- calcular `bundle_flag` com `chain_time` em segundos;
- escolher janela, horizonte ou critério depois de ver dado;
- usar o resultado como sinal de compra;
- juntar com o v61 num score único antes de cada um ter evidência própria.
