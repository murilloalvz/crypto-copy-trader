# Wallet Confirmation + Placebo v1

## Status

**METODOLOGIA CONGELADA / INFRAESTRUTURA ANALÍTICA IMPLEMENTADA / SEM EVIDÊNCIA DE EDGE.**

Arquivos:

- `src/wallet_confirmation_placebo.py`;
- `src/wallet_placebo_matching.py`;
- `src/wallet_confirmation_study.py`;
- `wallet_placebo_match.py`;
- `tests/test_wallet_confirmation_placebo.py`;
- `tests/test_wallet_placebo_matching.py`;
- `tests/test_wallet_confirmation_study.py`;
- `docs/wallet-placebo-matching-v1.md`.

A camada existe para responder uma pergunta antes de Wallet Confirmation virar estratégia:

> quando wallets selecionadas pelo nosso processo parecem confirmar uma oportunidade, elas acrescentam informação que não seria obtida por grupos de wallets apenas parecidos em atividade?

Sem placebo, a frase "duas smart wallets compraram" pode apenas significar que o token já estava popular.

## Hipótese

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

Para o primeiro estudo:

- janela: 300 segundos;
- confirmação: >=2 wallets únicas da coorte com BUY observado na janela.

Esses valores são parâmetros do **estudo**, não filtros da Wave nem autorização de trade. Devem permanecer congelados no primeiro estudo prospectivo; não fazer grid search e escolher a janela que ficou melhor depois.

## Coorte target

A target precisa ser formada antes dos outcomes do período de teste.

Pode usar somente evidência pré-período, como:

- evidence readiness;
- qualidade de sequência;
- repeatability/fingerprint;
- token breadth;
- intensidade em dia ativo;
- holding horizon;
- DEX mix;
- copyability/latency já observada antes do estudo.

As três wallets atuais do Forward Watch são uma coorte de observabilidade/arquéti​pos, não uma "smart-wallet basket" validada. Não devem ser fundidas automaticamente em uma confirmação econômica única.

## Placebo Matching v1

O matching pré-período está implementado em `src/wallet_placebo_matching.py` e documentado separadamente.

Ele não usa PnL/outcome futuro e não cria Match Score ponderado. Expõe separadamente:

- bucket similarity;
- active-day rate ratio;
- token breadth ratio;
- first-exit/holding ratio;
- observed span ratio;
- diferenças de roundtrip/scale-in/multi-sell/reentry;
- DEX dominante;
- warnings de coverage/evidence readiness.

A ordenação é lexicográfica/auditável. Isso reduz pseudo-precisão e deixa claro onde uma candidata difere da target.

CLI:

```powershell
python wallet_placebo_match.py <TARGET_ADDRESS> --all-local --min-swaps 20
```

O universo local atual ainda é estreito; portanto a existência do matching não significa que já temos placebos suficientemente bons.

## Placebos

Usar múltiplas coortes placebo. Ideal inicial: pelo menos 3 grupos quando o universo permitir.

Regras estruturais:

- target/placebos wallet-disjoint;
- nomes únicos;
- papel explícito `target`/`placebo`;
- mesmo número de wallets por coorte por padrão.

O matching qualitativo precisa ser congelado com dados pré-período. Dentro do possível, placebos devem ser semelhantes em:

- swaps por dia ativo;
- número de tokens;
- holding/fingerprint;
- atividade recente;
- DEX mix;
- cobertura de sequência;
- janela de observação.

Wallets completamente aleatórias/inativas não são controle suficiente.

## Registro prospectivo imutável

`src/wallet_confirmation_study.py` adiciona um registry local para pré-registrar o desenho **antes** do período de outcome.

O `ConfirmationStudySpec` congela:

- `study_key`;
- `preperiod_cutoff`;
- `frozen_at`;
- `starts_at` e opcional `ends_at`;
- target;
- placebos;
- regra de confirmação;
- horizontes;
- context scope;
- versão do matching;
- notas.

Uma `study_key` já registrada com configuração diferente é rejeitada. O registry também impede ativação antes de `starts_at`. Estados:

```text
FROZEN -> ACTIVE -> CLOSED
```

O registry não contém outcomes e não escolhe cohort automaticamente; ele existe para impedir que a configuração seja silenciosamente reescrita depois de vermos resultados.

## Mesma oportunidade, mesmo relógio

Target e placebos precisam ser avaliados no mesmo universo temporal.

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

O primeiro context scope suportado pelo registry é `wave_opportunity_v1`: a pergunta incremental é feita sobre oportunidades Wave, sem alterar a entrada Wave.

## Outcomes

A infraestrutura analítica suporta `completed`, `pending` e `failed`. Missingness permanece no denominador.

Resumo por coorte:

- eventos confirmados;
- completos/falhos/pendentes ou ausentes;
- cobertura;
- média/mediana;
- share >0;
- share >=+20%;
- share <=-25%.

Os cortes +20/-25 são descritivos, não TP/SL.

## Target x placebo

O comparador reporta:

- target menos mediana das médias dos placebos;
- target menos mediana das medianas;
- target menos mediana da taxa positiva.

Labels:

- `NO_COMPARABLE_OUTCOMES`;
- `DESCRIPTIVE_LOW_COVERAGE`;
- `DESCRIPTIVE_PLACEBO_COMPARISON`.

Nenhum significa `edge proven`.

## Critérios antes de promoção

Wallet Confirmation só merece avançar para Strategy Lab/Shadow se, prospectivamente:

1. target tiver amostra suficiente;
2. coverage/missingness forem comparáveis;
3. o efeito não depender de um único winner;
4. média/mediana forem coerentes o suficiente para interpretação;
5. target superar vários placebos, não só o pior;
6. aparecer em mais de um dia/regime;
7. quotes/latência mostrarem oportunidade depois da detecção;
8. custos/liquidez não apagarem o diferencial;
9. critério de sucesso tiver sido pré-declarado.

## Relação com Wave

Primeiro teste recomendado:

```text
Wave opportunity em t
-> target confirmou até t?
-> placebos confirmaram até t?
-> outcome futuro
```

Pergunta:

> entre oportunidades comparáveis do Wave, a confirmação target acrescenta informação além da atividade normal de wallets semelhantes?

`wave_v3_volume_integrity` permanece congelada enquanto a pergunta é respondida.

## Relação com Jupiter

Se houver sinal descritivo:

```text
wallet BUY observado
-> confirmação causal
-> delay real
-> quote/rota disponível
-> custo/slippage
-> outcome executável aproximado
```

Se o efeito desaparecer depois de +30–120s, ele não é copiável para nós, mesmo que exista no preço de referência.

## Próximo passo real

Ainda não existe universo/amostra suficiente para congelar um estudo econômico sério. Antes disso:

1. concluir Wallet Forward + Jupiter;
2. ampliar o universo de wallets quando a fonte permitir;
3. rodar matching somente com dados pré-período;
4. revisar coverage/warnings;
5. congelar target/placebos no registry;
6. só então iniciar o período prospectivo.
