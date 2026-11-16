# Rodada 22 — especificação do teste de efeito plantado (para a Fase C)

PAPER/READ-ONLY. **Só especificação**: nenhum código, nenhuma corrida, nenhum pré-registro.
Detector, parâmetros e hashes intocados (V3 `56762db29cd6`). O objetivo é provar, **antes** de olhar
dado limpo, que o pipeline inteiro (detector → entrada → custo → horizonte/marcação → comparação →
bootstrap/teste) faz duas coisas:
- **recupera** um efeito conhecido quando ele existe;
- **não inventa** efeito quando ele não existe.

Aqui "efeito plantado" é um teste do método, não um resultado de mercado.

## 1. Dados permitidos

- **Só tokens já queimados/vistos:**
  - os ~30 de replay/retro;
  - os de `pr_pools`;
  - as graduações da janela do piloto (16/10–01/11/2026).
- **Nunca** a janela limpa candidata (22/09 → início de `pr_pools`) nem o holdout selado do V0.
- O teste usa o **mesmo N de tokens** planejado para o B2, para medir o poder no tamanho real.
- Candles brutos ficam num cache próprio; o banco do bot nunca é aberto para escrita.

## 2. O que "enriquecimento k" significa

- **Evento binário:** `E` = tocar +2R antes de −1R dentro de 72h, a mesma definição de `varredura_v3`.
- **Taxa de base:** p0 = P(E | braço de comparação do B2), medida nos dados sem plantio.
- **Efeito plantado:** P(E | sinal) = k · p0, com **k ∈ {1,5; 2; 3}**.
  - Só é viável se k · p0 ≤ 1. Exemplo: com p0 ≈ 0,33, k=3 dá 0,99, no limite.
  - Se p0 medido > 0,33, k=3 fica fora do domínio e é registrado como tal, nunca truncado em silêncio.
- **Tradução para R:** o efeito equivalente em R médio (`dif_pareada`/R@72h) é calculado e reportado
  ao lado, porque é a métrica primária.

## 3. Mecanismo de plantio (modo A, pós-decisão — obrigatório)

1. Rodar o detector congelado uma vez por token; guardar `decision_ts`, `j0`, stop e TOPO de cada
   ENTRADA.
2. Para cada sinal (unidade = 1ª tentativa por token, `token_signal_seq==1`), sortear
   Z ~ Bernoulli(q).
   - Se Z=1, **substituir só os candles a partir de `j0`** por um segmento "runner" de biblioteca.
   - A biblioteca são segmentos reais pós-entrada que fizeram E, tirados do braço de comparação de
     **outros** tokens queimados.
   - O segmento é reescalado para o preço de entrada e a distância de stop do sinal: preço
     multiplicativo, OHLC coerente, volume original preservado.
3. **Calibração de q:** q = (k·p0 − p1)/(1 − p1), onde p1 = P(E | sinal) sem plantio.
   - O q fica congelado antes das réplicas.
4. **Invariantes verificados em toda réplica (falha = réplica inválida, contada):**
   - hash dos candles ≤ `decision_ts` idêntico antes/depois, o que garante que o plantio não mexeu
     na decisão;
   - o mesmo `DetectorV1` dispara o mesmo conjunto de ENTRADAs;
   - nenhum candle plantado aciona o veto (`razao_vizinho_max=10`, `close_vs_pico=3×pico`).
     A emenda do segmento é contínua: o 1º candle plantado abre no `open` original de `j0`;
   - custo, horizonte, marcação, veto e dedupe são os **mesmos objetos congelados**.
     O plantio nunca toca `CostModel`.
5. **Modo B (opcional, seleção de token):** plantar estrutura **antes** da decisão para testar a
   sensibilidade do detector. Só depois do modo A passar, e rotulado à parte; ele mexe no que o
   detector vê.

## 4. Réplicas, nulo e critérios

| cenário | réplicas | o que varia | o que se espera |
|---|---|---|---|
| nulo puro (sem plantio) | 1.000 | reamostragem de tokens com reposição | taxa de "positivo" ≈ α |
| nulo do mecanismo (plantio com mesmo q nos **dois** braços) | 1.000 | sorteio de Z + tokens | ≈ α (o mecanismo sozinho não cria efeito) |
| k = 1,5 / 2 / 3 | 200 cada | sorteio de Z + tokens | poder; viés; cobertura do IC |

"Positivo" = a regra de decisão que for pré-registrada para o B2, exatamente como escrita. Se a
regra usa α unilateral 0,05 (ou α/2 com Bonferroni), o alvo do nulo é esse α.

**Critérios de aceite (proposta; viram parte do pré-registro do B2, não decididos aqui):**
- **Falso positivo no nulo:** com 1.000 réplicas, a faixa binomial 95% em torno de 5% é
  **3,7%–6,4%**. Fora dela, o método não passa (para α=2,5%: 1,6%–3,5%).
- **Poder:** ≥ 80% no menor k de interesse (a definir; 2× é candidato) com o N planejado. Abaixo
  disso, o N do B2 sobe ou o B2 não roda.
- **Viés:** média do efeito estimado dentro de ±10% do efeito plantado (em R e em P(E)).
- **Cobertura:** o IC nominal de 90% cobre o efeito plantado em 85%–95% das réplicas.

Sementes: uma lista fixa (ex.: 20261201 + i), declarada antes da 1ª réplica.

## 5. Controles negativos (série sem estrutura temporal)

1. **Série invertida no tempo:** inverter a ordem dos candles; em cada candle trocar open↔close,
   manter high/low/volume; reetiquetar os timestamps em ordem crescente com o mesmo passo. Rodar o
   pipeline inteiro (detector incluso).
2. **Série embaralhada em blocos:** por token, decompor cada candle em retorno fechamento-a-fechamento
   + forma (o/h/l relativos ao close); embaralhar blocos de 6h e de 24h com semente fixa;
   reconstruir a partir do 1º preço. Isso preserva volatilidade e caudas e destrói a sequência.
3. **Entradas placebo:** instantes sorteados no mesmo pool, com a mesma fase/idade e a mesma
   distância de stop do sinal, no lugar das ENTRADAs do detector.

Nos três, espera-se "positivo" com frequência ≈ α em 200 reamostragens de tokens. Também se reporta
quantos sinais o detector gera em cada controle: menos sinais é esperado e não é falha.

## 6. Saída e limites

- **Reportar:**
  - curva de poder × k, com IC;
  - FP do nulo, com IC;
  - viés e cobertura;
  - nº de réplicas inválidas por invariante;
  - nº de sinais por controle negativo;
  - tempo de CPU.
- **Onde roda:** fora da VM (PC). Custo: o detector roda 1×/token; cada réplica só recalcula
  desfecho. Estimativa: minutos a poucas horas, não medido.
- **Este teste valida o método, não o mercado:**
  - passar não diz nada sobre a existência de efeito real;
  - falhar bloqueia o uso de dado limpo até o método ser corrigido. Um método corrigido é um método
    novo, que precisa passar de novo.
