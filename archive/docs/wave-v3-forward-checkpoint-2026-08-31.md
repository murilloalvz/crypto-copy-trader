# Wave v3 / Exit Engine forward checkpoint — 2026-08-31

## Contexto

Checkpoint produzido após a execução price-only de aproximadamente 5 horas durante a indisponibilidade de créditos da Solana Tracker Data API.

A execução não gerou novos discoveries/sinais. Ela continuou acompanhando e maturando posições/sinais já existentes. O resultado foi persistido no SQLite e auditado com:

```powershell
python evaluate.py --cohorts
python evaluate_exits.py
```

Modo em toda a avaliação: **PAPER / READ ONLY**.

## Wave v3

Estratégia: `wave_v3_volume_integrity`

- sinais registrados: 59;
- horizontes concluídos: 156;
- pendentes: 0;
- falhos: 21;
- snapshots legíveis: 59/59;
- snapshots sem pool de origem: 0;
- janelas de volume inconsistentes: 0.

### 5 minutos

- cobertura: 57/59 = 96,6%;
- falhas: 2;
- n: 57;
- win rate: 33,3%;
- retorno líquido médio: -0,44%;
- mediana: -1,60%;
- profit factor: 0,84;
- P&L paper total: US$ -6,31;
- drawdown acumulado paper: US$ 20,40;
- melhor/pior: +33,44% / -27,64%;
- média sem o melhor sinal: -1,05%;
- maior vencedor: 25,0% do lucro bruto.

Stress de slippage por lado:

- 0,5%: média +0,56%, mediana -0,61%, PF 1,25;
- 1,0%: média -0,44%, mediana -1,60%, PF 0,84;
- 2,0%: média -2,41%, mediana -3,55%, PF 0,42;
- 3,0%: média -4,35%, mediana -5,46%, PF 0,24.

**Leitura:** no estado atual, 5m não mostra edge líquido robusto e é muito sensível ao custo de execução.

### 15 minutos

- cobertura: 53/59 = 89,8%;
- falhas: 6;
- n: 53;
- win rate: 45,3%;
- retorno líquido médio: +2,08%;
- mediana: -1,15%;
- profit factor: 1,49;
- P&L paper total: US$ +27,54;
- drawdown acumulado paper: US$ 40,10;
- melhor/pior: +118,40% / -97,93%;
- média sem o melhor sinal: -0,16%;
- maior vencedor: 35,3% do lucro bruto.

Stress de slippage por lado:

- 0,5%: média +3,10%, PF 1,82;
- 1,0%: média +2,08%, PF 1,49;
- 2,0%: média +0,06%, PF 1,01;
- 3,0%: média -1,93%, PF 0,71.

**Leitura:** a média positiva desaparece ao remover o melhor trade. O horizonte continua interessante como hipótese, mas permanece dependente de cauda e com falhas de preço suficientes para exigir cautela.

### 60 minutos

- cobertura: 46/59 = 78,0%;
- falhas: 13;
- n: 46;
- win rate: 45,7%;
- retorno líquido médio: +5,28%;
- mediana: -0,14%;
- profit factor: 1,54;
- P&L paper total: US$ +60,76;
- drawdown acumulado paper: US$ 55,93;
- melhor/pior: +113,34% / -99,89%;
- média sem o melhor sinal: +2,88%;
- maior vencedor: 16,3% do lucro bruto.

Stress de slippage por lado:

- 0,5%: média +6,34%, PF 1,67;
- 1,0%: média +5,28%, PF 1,54;
- 2,0%: média +3,20%, PF 1,30;
- 3,0%: média +1,15%, PF 1,10.

**Leitura:** estruturalmente mais interessante que 5m/15m por manter média positiva sem o maior vencedor e suportar mais slippage, mas a cobertura de apenas 78% cria forte risco de survivorship. Não está validado.

## Coortes exploratórias

As coortes continuam exploratórias e não devem ser usadas para alterar filtros com menos de 30 observações por bucket.

Pontos que chamam atenção, sem promover regra:

- 5m não mostra melhora monotônica com Wave Score;
- 15m bucket 55–64,9 tem média positiva, mas n=29 e pode ser dominado por cauda;
- 60m Wave Score 75+ tem PF extremo, mas apenas n=5;
- 60m aceleração 1,50–1,99x tem média +39,38%, mas apenas n=4.

Esses números são exemplos clássicos de subconjuntos pequenos que podem parecer extraordinários por acaso. Não usar para tuning.

## Exit Engine v1

Coorte forward:

- `activated_at=1787964218`;
- `signal_id > 86`;
- intervalo esperado: 60s;
- sinais com todas as cinco políticas fechadas: **25**.

### `fixed_15m_v1`

- posições: 40;
- fechadas: 35;
- falhas: 5;
- cobertura: 87,5%;
- média/mediana: -1,94% / -1,68%;
- win rate: 34,3%;
- PF: 0,67;
- drawdown fechado: US$ 40,40;
- média sem melhor trade: -2,78%.

### `fixed_60m_v1`

- posições: 40;
- fechadas: 29;
- falhas: 11;
- cobertura: 72,5%;
- média/mediana: -4,45% / -1,26%;
- win rate: 27,6%;
- PF: 0,65;
- drawdown fechado: US$ 76,03;
- média sem melhor trade: -7,68%.

### `stop_loss_10_v1`

- posições: 40;
- fechadas: 33;
- falhas: 7;
- cobertura: 82,5%;
- média/mediana: -18,88% / -4,23%;
- win rate: 12,1%;
- PF: 0,10;
- pior trade: -99,96%;
- drawdown fechado: US$ 159,08.

### `take_profit_20_v1`

- posições: 40;
- fechadas: 32;
- falhas: 8;
- cobertura: 80,0%;
- média/mediana: +4,17% / -1,35%;
- win rate: 40,6%;
- PF: 2,29;
- pior/melhor: -29,43% / +25,32%;
- drawdown fechado: US$ 7,36;
- média sem melhor trade: +3,49%;
- maior vencedor: 10,7% do lucro bruto.

### `trailing_stop_10_v1`

- posições: 40;
- fechadas: 35;
- falhas: 5;
- cobertura: 87,5%;
- média/mediana: -17,80% / -4,68%;
- win rate: 14,3%;
- PF: 0,10;
- pior trade: -99,96%;
- drawdown fechado: US$ 159,56.

## Interpretação do Exit Engine

`take_profit_20_v1` é atualmente o braço **descritivamente mais interessante**, porque apresenta PF 2,29, média positiva sem o melhor trade e drawdown fechado muito menor. Isso **não** o torna vencedor: ainda há 20% de posições falhas, a amostra pareada completa é 25 e as coberturas entre políticas diferem.

Os resultados de `stop_loss_10_v1` e `trailing_stop_10_v1` mostram uma limitação semântica importante. Um stop chamado “10%” não equivale a execução garantida perto de -10% quando o mecanismo só reage a candles observados e concluídos. Em gaps/falhas, a saída ocorre no primeiro preço observado depois do cruzamento; por isso aparecem perdas próximas de -100%.

Esses braços não devem ser interpretados como teste fiel de um stop real executável. Uma eventual camada live precisa de quotes/routes executáveis e mecanismos de proteção compatíveis com a latência real.

## Decisão de pesquisa

1. `wave_v3_volume_integrity` permanece congelada; não afrouxar filtros para melhorar histórico.
2. 5m: hipótese enfraquecida no custo atual.
3. 15m: hipótese ainda aberta, mas cauda-dependente.
4. 60m: hipótese interessante, porém comprometida por cobertura/survivorship.
5. `take_profit_20_v1`: continuar observando; não declarar vencedor.
6. stop/trailing atuais: úteis para entender path/gaps, mas não como aproximação de execução live garantida.
7. Prioridade estratégica migra para Wallet Strategy Intelligence + Social/X + Opportunity Context, mantendo a coleta forward independente.
8. Próximo marco do exit engine continua sendo ampliar a quantidade de sinais forward totalmente pareados 5/5 antes de selecionar política.
