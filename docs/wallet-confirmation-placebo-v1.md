# Wallet Confirmation + Placebo v1

## Status

**METODOLOGIA CONGELADA / INFRAESTRUTURA ANALÍTICA IMPLEMENTADA / SEM EVIDÊNCIA DE EDGE.**

Arquivos:

- `src/wallet_confirmation_placebo.py`;
- `tests/test_wallet_confirmation_placebo.py`.

A camada existe para responder uma pergunta antes de Wallet Confirmation virar estratégia:

> quando wallets selecionadas pelo nosso processo parecem confirmar uma oportunidade, elas acrescentam informação que não seria obtida por grupos de wallets apenas parecidos em atividade?

Sem placebo, a frase "duas smart wallets compraram" pode apenas significar que o token já estava popular.

## Hipótese

Hipótese de pesquisa:

```text
confirmação por uma coorte target pré-selecionada
TEM outcome futuro diferente
DE confirmações geradas por coortes placebo comparáveis
```

Isso não é assumido verdadeiro.

## Unidade causal

Cada observação é definida por:

- token;
- `as_of`;
- coorte de wallets;
- janela retrospectiva congelada;
- número de wallets únicas com BUY realmente **observado até `as_of`**;
- outcome posterior em horizonte explícito.

`chain_time` histórico sincronizado depois não pode voltar no tempo e criar confirmação retroativa. A disponibilidade causal é definida por `observed_at`.

## Regra primária de confirmação v1

Para a infraestrutura inicial:

- janela: 300 segundos;
- confirmação: >=2 wallets únicas da coorte com BUY observado na janela.

Esses valores são parâmetros do **estudo**, não filtros da Wave nem autorização de trade. Eles devem permanecer congelados no primeiro estudo prospectivo; não fazer grid search 30s/60s/5m/15m e escolher o que ficou melhor depois.

## Coorte target

A target deve ser formada **antes** de olhar os outcomes do período de teste.

Critérios de seleção podem usar somente informação pré-período, como:

- evidence readiness;
- qualidade de sequência observada;
- repeatability do fingerprint;
- token breadth;
- intensidade de atividade;
- holding horizon;
- DEX mix;
- copyability/latency quando disponível.

Não selecionar wallet porque ela acertou especificamente os tokens que serão usados para medir o estudo.

As três wallets atuais do Forward Watch são uma coorte de observabilidade/arquéti​pos, não uma "smart-wallet basket" já validada. Elas não devem ser fundidas automaticamente em uma confirmação econômica única.

## Placebos

Usar múltiplas coortes placebo. Ideal inicial: pelo menos 3 grupos.

Regras estruturais já suportadas pelo código:

- wallets target e placebo precisam ser disjuntas;
- nomes de coorte únicos;
- papel explícito `target`/`placebo`;
- por padrão, mesmo número de wallets em cada coorte.

O matching qualitativo precisa ser documentado com dados do pré-período. Os placebos devem ser parecidos, dentro do possível, em:

- swaps por dia ativo;
- número de tokens distintos;
- holding horizon/fingerprint;
- atividade recente;
- DEX mix;
- cobertura de sequência;
- janela de observação.

Não usar wallets completamente aleatórias/inativas como único placebo, porque seria um controle fácil demais.

## Mesma oportunidade, mesmo relógio

O estudo deve construir target e placebos sobre o mesmo universo de timestamps/oportunidades.

Exemplo:

```text
as_of t0 / token X
  target -> confirmou ou não
  placebo A -> confirmou ou não
  placebo B -> confirmou ou não
  placebo C -> confirmou ou não

as_of t1 / token Y
  target -> confirmou ou não
  mesmos placebos -> confirmou ou não
```

Isso reduz o risco de comparar uma coorte em dias/regimes favoráveis contra outra em mercado diferente.

## Outcomes

A infraestrutura suporta outcomes `completed`, `pending` e `failed` por horizonte. Missingness permanece no denominador.

Resumo por coorte:

- eventos confirmados;
- outcomes completos;
- falhos;
- pendentes/ausentes;
- cobertura;
- média;
- mediana;
- proporção >0;
- proporção >=+20%;
- proporção <=-25%.

Os cortes +20/-25 são descritivos, não TP/SL.

## Comparação target x placebo

O comparador calcula, de forma descritiva:

- target minus mediana das médias dos placebos;
- target minus mediana das medianas dos placebos;
- target minus mediana da taxa positiva dos placebos.

Labels possíveis:

- `NO_COMPARABLE_OUTCOMES`;
- `DESCRIPTIVE_LOW_COVERAGE`;
- `DESCRIPTIVE_PLACEBO_COMPARISON`.

Nenhum label significa "edge proven".

## Critérios antes de promoção

Wallet Confirmation só merece avançar para Strategy Lab/Shadow se, prospectivamente:

1. target tiver amostra suficiente de confirmações;
2. cobertura/missingness forem comparáveis entre target e placebos;
3. o efeito não depender de um único token vencedor;
4. média e mediana não contarem histórias totalmente incompatíveis;
5. target superar vários placebos, não só o pior deles;
6. o efeito aparecer em mais de um dia/regime;
7. latency/quotes reais mostrarem que ainda existe oportunidade depois da detecção;
8. custos e liquidez não apagarem o diferencial;
9. o critério de sucesso tiver sido declarado antes de abrir o outcome final.

## Relação com Wallet Strategy Intelligence

Os fingerprints continuam úteis para duas coisas diferentes:

1. escolher a target de forma defensável;
2. construir placebos de atividade/arquetipo semelhante.

Eles não provam que a wallet é boa para copiar.

Exemplo futuro:

```text
7mPti-like target
vs
placebos com holding/atividade parecidos
```

é metodologicamente melhor do que:

```text
wallet lucrativa
vs
wallets aleatórias inativas
```

## Relação com Wave

Primeiro teste recomendado é incremental, não substitutivo:

```text
Wave opportunity em t
-> target wallets confirmaram até t?
-> placebos também confirmaram?
-> outcome futuro
```

Pergunta:

> entre oportunidades comparáveis do Wave, a confirmação target acrescenta algo além da atividade normal de wallets semelhantes?

Não alterar `wave_v3_volume_integrity` enquanto essa pergunta estiver sendo respondida.

## Relação com Jupiter

Se Wallet Confirmation mostrar sinal descritivo, o próximo gate usa a infraestrutura Wallet Forward + Jupiter:

```text
wallet BUY observado
-> confirmação causal
-> delay real
-> quote/rota disponível
-> custo/slippage
-> outcome executável aproximado
```

Um efeito que existe no preço de referência mas desaparece depois de 30–120s não é copiável para nós.

## Próximo passo real

Ainda não existe amostra prospectiva suficiente para executar este estudo de forma séria. Primeiro precisamos:

1. concluir a coleta Wallet Forward + Jupiter;
2. aumentar o universo de wallets pesquisadas quando a fonte permitir;
3. formar target e placebos usando somente dados pré-período;
4. congelar os grupos;
5. iniciar a coleta prospectiva do estudo.
