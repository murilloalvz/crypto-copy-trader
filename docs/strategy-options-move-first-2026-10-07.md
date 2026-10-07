# Opções de estratégia — "move first" — 2026-10-07

## Status

RESEARCH / PAPER / READ ONLY. Documento de pesquisa. Nenhum pré-registro aberto por este memo, nenhuma coleta rodada, nenhuma rede de produção tocada, nenhum threshold congelado alterado, nenhum resultado fechado reaberto.

## Diagnóstico que motiva este memo

Registro de hipóteses: ~15 veredictos econômicos, 0 `VALIDADA`. Seletores de minuto inicial (V48, V55→V68, PQ-V1) nunca foram lucrativos mesmo no grupo favorável; V68 separou LOW/HIGH mas LOW ficou negativo. O padrão: no memecoin solana, quem ganha nos primeiros minutos ganha por **posição** (deployer, insider, MEV, KOL com acesso prévio), não por **padrão** replicável depois do fato. Sendo read-only, chegando segundos depois, com ordens de ~US$25 e sem MEV, copiar o gatilho de entrada desse grupo é estruturalmente apostar do lado de quem fornece liquidez de saída pra eles — não do lado deles. Evidência: E11 (copier ~3% vs smart money ~14% sob fricções realistas) e E12 (>55% dos snipers saem em <1min, >85% em <5min, 87% dos snipers lucrativos). Filtros de rejeição (PQ-TR) evitam perda, mas não criam lucro — perfil de "sobrevivente", não de "fonte". Prioridade nova: achar a **fonte** de lucro antes de voltar a empilhar filtro.

## Regra de qualificação para a recomendação (nova, 2026-10-07)

Só entra na recomendação final a opção que responder, com evidência, às 5 perguntas:

1. **De quem vem o dinheiro** — contraparte que perde e por quê.
2. **Por que conseguimos capturar** sendo read-only, segundos atrasados, ordens de ~US$25, sem MEV.
3. **Qual evidência** (nossa ou externa séria) mostra que essa sobra existe.
4. **Qual o teste mais barato e decisivo.**
5. **Qual o critério de morte**, escrito antes.

Opção que não responde às 5 fica listada como **DESCARTADA**, com o motivo. No fim, no máximo 2 caminhos são recomendados. Cada um recomendado terá exatamente **1 discovery + 1 confirmação**. Regra de parada: **se nenhum dos caminhos recomendados der resultado positivo líquido de custos (Gate 2), o programa de memecoin é encerrado.** Esta regra de parada também foi escrita em `docs/research-hypothesis-registry-v1-2026-10-04.md`.

---

## Opção A — Post-Transition Pullback-Reacceleration V1

1. **Fonte de movimento positivo e por quê**: hipótese de reversão — token pulla (recua) depois do impulso inicial e depois reacelera; o mecanismo alegado é que vendedores de pânico vendem no fundo do recuo e compradores de momentum compram de novo na reaceleração.
2. **Por que a desvantagem de velocidade não mataria**: a geometria de recuo/reaceleração é definida em segundos a minutos (decisão fixada em `transition_observed_at + 30s`, rótulos em +60s/+300s), não em blocos/sub-segundo — em tese um atraso de poucos segundos não destrói o sinal se o padrão for real.
3. **Evidência**: **nenhuma própria** — a V0 (`research/post-transition-pullback-reacceleration-v0`) queimou com `conditional_economic_n = 0` (2 episódios, ambos rejeitados por price-impact indisponível) e um gap de cobertura causal separado (lineage Pump→PumpSwap não observada nas sondas curtas). Evidência externa indireta (E2/E3/E5 — momentum/reversão em cripto) já é classificada no próprio registro como "não transfere automaticamente" para horizonte de segundos em memecoin Solana. E a evidência externa mais próxima do nosso domínio (`docs/external-evidence-reuse-map-v1.md` — "A Midsummer Meme's Dream": 82,89% dos tokens com retorno >100% mostram mecanismo de crescimento artificial) **corta contra** a leitura de reversão orgânica: se a maioria dos candidatos de alto retorno é pump artificial, reacelerar depois de um recuo tem boa chance de ser continuação do mesmo pump artificial, não uma sobra capturável de pânico genuíno.
4. **Teste mais barato**: descoberta curta reaproveitando o protocolo V0 já escrito, corrigindo a semântica de price-impact (`abs(priceImpact)` em vez de rejeitar sinal negativo) — mas isso ainda não resolve o gap de cobertura causal nem a evidência que falta no item 3.
5. **Critério de morte**: poderia ser escrito (ex.: direção não replica, ou `conditional_economic_n` não atinge o mínimo de novo).

**Veredito: DESCARTADA.** Falha a pergunta 3: zero evidência própria (tentativa já queimada, n=0) e a evidência externa mais próxima do domínio aponta na direção contrária (mecanismo provavelmente artificial, não reversão orgânica). Reabrir V1 sem antes resolver isso seria gastar uma tentativa nova sobre a mesma incerteza que já queimou a V0.

---

## Opção B — Descoberta "movement first" em horizontes longos (1h/4h/24h), sem gatilho de entrada fixo

1. **Fonte de movimento positivo e por quê**: a própria E12 mostra que o grupo adversário que nos bate na janela de segundos (snipers com pré-financiamento direto do deployer) **sai sozinho** — >55% saem em <1min, >85% em <5min. Um token que continua negociando de forma não-morta depois dessa janela já filtrou, por construção, boa parte da atividade puramente insider/sniper de curtíssimo prazo. A fonte de retorno em 1h/4h/24h não é "vencer" quem tem posição privilegiada no bloco 0 — é observar, depois que esse grupo já saiu, se o que resta tem dinâmica de fluxo (participação, diversidade de carteira, ausência de dominância de uma única carteira) que precede continuação de movimento.
2. **Por que a desvantagem de velocidade não mataria**: a decisão não compete no relógio de segundos — o sinal de entrada, se existir, é lido em janelas de minutos (ex.: +5min) e a posição é avaliada em 1h/4h/24h. Segundos de atraso, read-only, ordem de ~US$25, sem MEV, não têm o mesmo custo relativo que têm na disputa de bloco 0.
3. **Evidência**: própria, nenhuma ainda (seria descoberta nova) — mas a evidência externa que já temos (E12: estrutura temporal de saída de snipers) e o próprio padrão interno do programa (V48/V55/V68 falharam todos olhando o minuto 0-15; nenhuma tentativa testou o que sobra depois da janela de saída do sniper) apontam um espaço ainda não testado, logicamente consistente com o mecanismo do item 1. `ROUTE_RESEARCH_HORIZONS_SECONDS = (300, 900, 3600)` já está congelado e suportado em `src/opportunity_route_research_store.py` — o contrato de armazenamento para 1h já existe; só o coletor ativo (`route_research_forward_collection_900_v0.py`) hoje só puxa (300, 900).
4. **Teste mais barato e decisivo**: descoberta observacional (sem execução, sem nova infra de ordem) sobre dados já causais: medir, para tokens ainda negociando em +5min, se um marcador simples e causalmente disponível em +5min (ex.: fluxo ainda ativo, sem dominância de carteira única) separa quem segue positivo em +1h/+4h/+24h. Requer habilitar o polling de 3600s no coletor existente (usar capacidade já suportada, não é tocar threshold congelado) — isso fica para a fase de pré-registro, não decidido aqui.
5. **Critério de morte**: se a descoberta não mostrar separação de direção com suporte mínimo (n≥30 pares, disciplina já usada em EBPQ/CHURN), ou se a confirmação fresh não replicar a mesma regra congelada, ou se o resultado líquido de custos (Gate 2) não for positivo — fecha, sem reabrir com outro horizonte/feature/combinação.

**Veredito: SOBREVIVE.** Única opção com uma história de contraparte específica e testável (quem sai cedo, por que o que resta é outra população), consistente com evidência externa que já temos (E12), e um teste barato que reaproveita infraestrutura já existente sem tocar nada congelado.

---

## Opção C — Stack de filtros como camada sobre A/B

1-5. Por definição, C **não tem fonte própria de dinheiro** — ela não reivindica de onde vem o lucro, só reivindica reduzir perdas sobre um sinal de entrada que já exista. Não responde à pergunta 1 de forma independente (não há contraparte perdendo *para C*; C só filtra a cauda ruim de outra coisa). É explicitamente contingente a A ou B produzirem um sinal de entrada primeiro.

**Veredito: DESCARTADA** (como caminho independente). Motivo: falha a pergunta 1 por construção — é uma camada, não uma fonte. Fica registrada como passo futuro condicional se e quando B (a opção sobrevivente) produzir um sinal de entrada para filtrar — não como um dos no-máximo-2 caminhos recomendados agora.

---

## Opção D — Robinhood Chain / Pons

1. **Fonte de movimento positivo e por quê**: argumento de imaturidade de mercado — chain nova (id 4663), poucos bots/MEV estabelecidos ainda, logo a vantagem posicional que nos bate em Solana talvez não esteja totalmente competida lá.
2. **Por que a desvantagem de velocidade não mataria**: se a infraestrutura de sniping/MEV ainda não existe nesse mercado, ser segundos atrasado pode não ser fatal — é a aposta central de D.
3. **Evidência**: **nenhuma, nem própria nem externa.** As branches relacionadas (`feat/robinhood-sequencer-shadow-v0`, `feat/pons-direct-quote-v0`, `research/robinhood-launch-burst-v0`, `fix/robinhood-public-rpc-ua-v0`) são 100% plumbing/adapter/pesquisa de viabilidade (curve-quote direto via `eth_call`, feed Nitro intent-only) — nenhuma coleta econômica, nenhum episódio, nenhum resultado. Não foi encontrado nenhum estudo externo (peer-reviewed, preprint ou mesmo informal tipo Pine Analytics) específico de Robinhood Chain/Pons — a chain é recente demais (docs datados de 2026-09-08 a 09-15). O feed de sequenciador Nitro é intent-only (visibilidade de pré-confirmação), o que ajuda latência/missingness de pesquisa mas **não confere vantagem de velocidade de execução** — já documentado explicitamente no protocolo da própria branch.
4. **Teste mais barato**: exigiria construir um coletor econômico causal do zero (hoje só existe math de cotação e adapters de leitura) — caro na comparação com A/B, que reaproveitam infraestrutura já causal.
5. **Critério de morte**: moot — não há pergunta 3 respondida para ter o que matar ainda.

**Veredito: DESCARTADA.** Falha a pergunta 3 de forma total: zero evidência própria (nunca coletamos economia nesse mercado) e zero evidência externa séria encontrada. "Mercado mais novo" é uma hipótese plausível, não uma evidência.

---

## Opção E — Parar o programa, só acumular dados baratos

Não é uma hipótese de lucro — não reivindica fonte, não compete pelas 5 perguntas. É a consequência automática da regra de parada: se B (única sobrevivente) não passar discovery + confirmação líquida de custos, o programa de memecoin se encerra e o que resta é acumulação de dados a custo baixo, sem mais tentativa econômica nova, até nova evidência justificar reabrir.

---

## Recomendação final (decisão é minha, do operador)

Caminho único recomendado: **B — "movement first" em horizontes longos**, com desenho 1 discovery + 1 confirmação:

- **B-DISC-V0** (a pré-registrar, não aberto por este memo): marcador causal em +5min (fluxo ainda ativo / sem dominância de carteira única) vs retorno em +1h/+4h/+24h, amostra mínima n≥30 pares primários, direção fixada antes da coleta, horizonte 3600s habilitado no coletor existente (capacidade já suportada, nenhum threshold congelado tocado).
- **B-CONF-V0**: replicação fresh da mesma regra congelada do discovery (mesmo corte, mesma direção, amostra nova), mesma disciplina de 3 passos do registro (PASS → replicação → Gate 2 líquido de custos) antes de `VALIDADA`.

A (Post-Transition V1), C (filtro como camada) e D (Robinhood/Pons) ficam **DESCARTADAS** pelos motivos acima — não voltam a este memo sem evidência nova que resolva especificamente o que faltou (A: evidência própria ou externa a favor, não contra; D: qualquer evidência própria ou externa que hoje não existe).

**Regra de parada**: se B não passar discovery → confirmação → líquido de custos (Gate 2), o programa de memecoin é encerrado, conforme regra escrita acima e replicada em `docs/research-hypothesis-registry-v1-2026-10-04.md`.

Nenhum pré-registro foi aberto por este memo. Nenhuma coleta foi rodada. Nenhum threshold congelado foi alterado. Nenhum resultado fechado foi reaberto.
