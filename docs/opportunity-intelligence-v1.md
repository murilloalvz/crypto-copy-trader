# Opportunity Intelligence v1

## Status

PLANEJADO como arquitetura de pesquisa. A camada causal básica de eventos sociais já está IMPLEMENTADA em `src/social_intelligence.py`. Wallet Strategy Lab v1 também está IMPLEMENTADO. Nenhum destes componentes altera automaticamente `wave_v3_volume_integrity`.

## Tese

O projeto não deve depender de um único gatilho. A hipótese de pesquisa passa a ser:

```text
mercado / Wave
      +
wallet behavior
      +
social / X
      ↓
opportunity context
      ↓
strategy hypothesis
      ↓
causal replay → execution stress → shadow
```

A meta não é criar um score alto por somar indicadores. A meta é medir se sinais independentes, disponíveis antes da decisão, acrescentam informação sobre o resultado futuro e se esse ganho sobrevive à execução realista.

## Sensores

### 1. Market / Wave

`wave_v3_volume_integrity` continua congelada enquanto a coleta forward existente amadurece. Ela é uma fonte de oportunidade de mercado, não necessariamente a estratégia final inteira.

### 2. Wallet Strategy Intelligence

O Wallet Strategy Lab compara comportamento de várias wallets sem exigir a Solana Tracker Data API. Ele descreve holding, frequência, scale-in, reentry, full exit versus staged exit, runner observado e DEX mix.

O objetivo é descobrir padrões repetidos entre wallets, não copiar uma transação individual depois que ela já aconteceu.

### 3. Social / X Intelligence

O tracker social futuro deve registrar eventos com dois tempos separados:

- `created_at`: quando o post/evento foi publicado;
- `observed_at`: quando nosso coletor realmente tomou conhecimento dele.

Replay histórico só pode usar eventos cujo `observed_at <= decision_time`. Essa regra evita um look-ahead sutil em que um post antigo, descoberto horas depois, seria tratado como se o bot o conhecesse desde a publicação.

A fundação atual também permite snapshots repetidos do mesmo post. Em cada decisão histórica, somente o snapshot de engajamento mais recente já observado naquele instante pode ser usado.

## Social features v1

A primeira versão é deliberadamente descritiva e não possui pesos de trading.

Para janelas como 5m, 15m e 60m ela mede:

- quantidade de eventos;
- autores únicos;
- posts originais;
- reposts/quotes;
- likes;
- reposts;
- replies;
- quotes.

Essas métricas só viram sinal depois de testes causais. Não existe no v1 uma regra como "muitos likes = comprar".

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
- comportamento por regime/arquetipo;
- taxas/slippage;
- atraso de detecção e execução;
- liquidez executável.

## Strategy Router

O Strategy Router permanece PLANEJADO. Ele só deve existir depois que mais de um arquétipo de estratégia tiver evidência própria.

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

## Ordem de construção

1. ampliar Wallet Strategy Lab para múltiplas wallets;
2. conseguir uma nova fonte/coorte de wallets sem confundir research com copyability;
3. implementar coletor social/X com timestamps de observação;
4. persistir eventos e resolver mint/token com segurança;
5. juntar contextos apenas por informação disponível no instante da decisão;
6. fazer replay causal de hipóteses pré-declaradas;
7. stress de taxas, slippage, liquidez e atraso;
8. promover sobreviventes para shadow concorrente;
9. só então considerar Strategy Router e eventual live controlado.

## Regra de ouro

Uma narrativa convincente não é edge. Um padrão visual bonito não é edge. Uma wallet lucrativa não é automaticamente copiável. Um post viral não é automaticamente antecipador.

O projeto só promove uma hipótese quando o efeito aparece causalmente, sobrevive a custos e atraso e continua existindo em dados que não foram usados para inventar a regra.
