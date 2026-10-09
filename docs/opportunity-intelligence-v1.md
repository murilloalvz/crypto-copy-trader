# Opportunity Intelligence v1

## Status

**IMPLEMENTADO como infraestrutura de pesquisa** em `src/opportunity_intelligence.py`, `src/social_intelligence.py` e `src/social_features.py`. Wallet Strategy Lab e comparação cross-wallet também estão implementados. Nenhum destes componentes altera automaticamente `wave_v3_volume_integrity` e nenhum deles gera ordem.

## Tese

O projeto não deve depender de um único gatilho. A hipótese de pesquisa passa a ser:

```text
mercado / Wave
      +
wallet behavior
      +
social / X
      ↓
causal opportunity context
      ↓
strategy hypothesis
      ↓
causal replay → execution stress → shadow
```

A meta não é criar um score alto por somar indicadores. A meta é medir se sinais independentes, disponíveis antes da decisão, acrescentam informação sobre o resultado futuro e se esse ganho sobrevive à execução realista.

## Contrato temporal

O ponto central desta camada é distinguir o momento em que algo aconteceu do momento em que o sistema realmente soube disso.

- Wave usa `detected_at`.
- Wallet usa `chain_time` **e** `observed_at`.
- Social usa `created_at` **e** `observed_at`.
- Um contexto em `as_of=T` só pode usar informações com `observed_at <= T` ou `detected_at <= T`.

Isso impede um erro grave de replay: sincronizar depois uma transação antiga e fingir que o bot conhecia aquela compra no momento original da blockchain.

## 1. Market / Wave

`wave_v3_volume_integrity` continua congelada enquanto a coleta forward existente amadurece. Ela é uma fonte de oportunidade de mercado, não necessariamente a estratégia final inteira.

`WaveOpportunityEvidence` só entra no contexto quando `detected_at <= as_of`.

## 2. Wallet Strategy Intelligence

O Wallet Strategy Lab compara comportamento de várias wallets sem exigir a Solana Tracker Data API. Ele descreve holding, frequência, scale-in, reentry, full exit versus staged exit, runner observado e DEX mix.

A comparação cross-wallet separa recorrência de padrão de qualidade da evidência. Uma fingerprint repetida serve para formular hipótese; não prova PnL, intenção ou copyability.

### Regra causal para wallets

`WalletActionObservation` exige `chain_time` e `observed_at`. O SQLite histórico atual de `transactions` registra `block_time`, mas não registra o instante real em que um futuro coletor live viu a transação.

Portanto, backfill RPC atual é útil para reconstrução comportamental, mas **não deve ser usado como prova de confirmação live histórica ou latência de cópia**. Antes de medir `wallet entrou → nosso sistema decidiu`, será necessário um coletor forward que persista o instante de observação.

## 3. Social / X Intelligence

Eventos sociais usam dois tempos separados:

- `created_at`: quando o post/evento foi publicado;
- `observed_at`: quando nosso coletor realmente tomou conhecimento dele.

Replay histórico só pode usar eventos cujo `observed_at <= decision_time`. Essa regra evita um look-ahead sutil em que um post antigo, descoberto horas depois, seria tratado como se o bot o conhecesse desde a publicação.

### Snapshot de engagement sem falso burst

A camada social foi endurecida para snapshots repetidos do mesmo post:

- entrada do post em uma janela = **primeira vez em que o coletor o observou**;
- likes/reposts/replies/quotes = snapshot mais recente que já era observável em `as_of`;
- uma atualização de engagement horas depois não transforma um post antigo em nova menção de 5 minutos.

Isso evita um falso sinal social que poderia inflar artificialmente bursts em replay.

## Social features v1

`SocialBurstFeatures` é deliberadamente descritivo e não possui pesos de trading.

Ele mede:

- quantidade de eventos na janela recente;
- autores únicos;
- taxa de eventos por minuto;
- quantidade/taxa na parte anterior e não sobreposta da janela-base;
- razão de aceleração quando existe baseline anterior;
- diversidade de autores;
- proporção de posts originais;
- engagement total e por evento observado.

Se o baseline anterior for zero, a razão de aceleração fica `None` em vez de virar infinito. Nenhuma regra atual chama o resultado de bullish, viral ou tradeable.

## Opportunity Context

`OpportunityContextSnapshot` junta os canais que estavam realmente disponíveis em `as_of` e expõe:

- evidência Wave elegível;
- compras/vendas de wallets já observadas;
- quantidade de wallets únicas comprando/vendendo;
- features sociais causais;
- lista de canais disponíveis.

Não existe `score`, peso `Wave + Wallet + X`, threshold de compra ou escolha automática de política nesta fase.

Isso é deliberado. Pesos só devem surgir depois que replay causal e forward/shadow mostrarem ganho incremental fora da amostra.

## Identidade do token

Símbolos sozinhos são ambíguos. O caminho preferencial é resolver evento social para contrato/mint e manter `symbol` apenas como informação auxiliar. Casos sem resolução segura devem ser marcados como ambíguos e não associados automaticamente a um token.

## X/source adapter

O coletor real de X ainda não está implementado. Quando for construído, deve usar uma fonte autorizada/estável e persistir dados brutos antes de qualquer classificação. O parser e as features causais devem permanecer independentes do provedor para permitir trocar a fonte sem mudar a definição do experimento.

## Experimentos que realmente importam

Para cada oportunidade devemos poder comparar, no mesmo horizonte e universo:

- Wave sozinho;
- wallet evidence sozinho;
- social evidence sozinho;
- Wave + wallet;
- Wave + social;
- wallet + social;
- Wave + wallet + social.

A combinação só é interessante se acrescentar desempenho fora da amostra e não apenas selecionar retrospectivamente os maiores pumps.

Métricas mínimas:

- cobertura e falhas;
- tamanho da amostra;
- retorno médio e mediano;
- win rate com incerteza;
- profit factor;
- drawdown;
- MFE/MAE;
- dependência dos maiores vencedores;
- comportamento por regime/arquétipo;
- taxas/slippage;
- atraso de detecção e execução;
- liquidez executável.

## Strategy Router

O Strategy Router permanece **PLANEJADO**. Ele só deve existir depois que mais de um arquétipo de estratégia tiver evidência própria.

Possível fluxo futuro:

```text
opportunity
  ↓
causal context
  ↓
classificação de regime / arquétipo
  ↓
política de entrada e gestão pré-declarada
  ↓
shadow concorrente
```

Não devemos treinar um roteador para escolher, olhando para trás, qual política teria vencido cada trade. Isso criaria leakage de seleção.

## Ordem de construção atual

1. ampliar a coorte multi-wallet e procurar fingerprints recorrentes;
2. obter novas wallets sem confundir research com copyability;
3. construir coletor forward de wallet actions com `observed_at` real;
4. implementar coletor social/X com timestamps de observação;
5. persistir eventos e resolver mint/token com segurança;
6. juntar contextos apenas por informação disponível no instante da decisão;
7. fazer replay causal de hipóteses pré-declaradas;
8. stress de taxas, slippage, liquidez e atraso;
9. promover sobreviventes para shadow concorrente;
10. só então considerar Strategy Router e eventual live controlado.

## Regra de ouro

Uma narrativa convincente não é edge. Um padrão visual bonito não é edge. Uma wallet lucrativa não é automaticamente copiável. Um post viral não é automaticamente antecipador.

O projeto só promove uma hipótese quando o efeito aparece causalmente, sobrevive a custos e atraso e continua existindo em dados que não foram usados para inventar a regra.
