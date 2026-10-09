# Wallet Intelligence v1 — first real scan (2026-08-30)

Status: **RESEARCH / READ ONLY**

A `wave_v3_volume_integrity` permanece congelada. Esta rodada não altera filtros, scoring econômico, políticas de saída ou qualquer caminho de execução.

## Configuração observada

- universo solicitado: 250 wallets
- top para análise: 10
- copyability limit: 25
- liquid seeds: 25
- posições por perfil: 100

## Resultado do funil

- 250 fontes
- 2 wallets chegaram ao Candidate Score
- 2 foram avaliadas por Copyability
- nenhuma passou simultaneamente pelos gates mínimos de deep dive

A decisão metodológica é **não afrouxar critérios para forçar candidatas**. O próximo passo é aumentar a cobertura do universo de busca e observar os motivos de eliminação com telemetria explícita.

## Wallet 1 — 7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH

- Candidate Score: 85.7
- Copyability Score: 66.1
- arquétipo: position
- 19 posições
- PnL realizado da amostra: +US$431.11
- ROI mediano: +2.2%
- hold mediano: 6.1 dias
- maior vencedor: 25.5% do lucro bruto
- PnL sem maior vencedor: +US$318.91
- capital em tokens atualmente líquidos: 54.3%
- alertas: `liquid_capital_share_low`, `onchain_sequence_sample_small`

Leitura: perfil econômico relativamente menos dependente de um único outlier e horizonte longo, mas ainda abaixo do gate de 60% de capital em tokens líquidos. Não promover. É uma wallet útil para ampliar evidência e, se necessário, investigar como caso quase-copyable sem tratá-la como aprovada.

## Wallet 2 — 24CFyAuCW4qZqeRFqMagtFdw1DiB86Pm7MXB21QF5TES

- Candidate Score: 85.8
- Copyability Score: 20.1
- arquétipo: intraday
- 100 posições
- PnL realizado da amostra: +US$8,286.11
- ROI mediano: 0.0%
- hold mediano: 33.1 minutos
- maior vencedor: 31.8% do lucro bruto
- PnL sem maior vencedor: +US$5,415.28
- capital em tokens atualmente líquidos: 0.0%
- alertas: `positive_pnl_with_nonpositive_median_roi`, `liquid_capital_share_low`, `onchain_sequence_sample_small`

Leitura: PnL agregado forte, porém mediana não positiva e nenhuma fração de capital classificada como atualmente líquida na amostra. Não é candidata de deep dive neste estado. Serve como exemplo de por que PnL agregado não pode ser usado sozinho para selecionar wallets.

## Próxima rodada

Aumentar o universo sem alterar os gates:

- 1,000 wallets
- até 200 liquid-market seeds
- até 100 candidatas avaliadas por copyability
- 100 posições por perfil

O scanner passa a imprimir também as principais eliminações do Candidate Score e as barreiras de Copyability, para identificar se o gargalo é qualidade econômica, frequência/holding, liquidez, concentração ou cobertura de dados.

Se ainda não surgirem candidatas de deep dive, a próxima mudança deve ser de **source coverage / discovery design**, e não de relaxamento dos critérios de segurança/copyability.
