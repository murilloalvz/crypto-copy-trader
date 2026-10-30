# Wallet Forward Convergence v1

## Status

**IMPLEMENTADO / TESTADO EM SUÍTE / AGUARDANDO AMOSTRA OPERACIONAL.**

Esta camada é somente `RESEARCH / READ ONLY`. Ela não cria sinal, não altera `wave_v3_volume_integrity`, não escolhe token, não calcula edge/PnL e não envia ordem.

O objetivo é aproveitar as mesmas observações causais da coleta Wallet Forward para responder uma pergunta mais específica:

> duas ou mais wallets monitoradas compraram o mesmo token dentro de uma janela curta **e nós já sabíamos disso naquele instante**?

Isso cria uma ponte entre Wallet Intelligence e o futuro estudo de Wallet Confirmation, sem confundir convergência com prova de vantagem informacional.

## Regra v1

Padrão do relatório:

- somente ações `BUY` realmente observadas em forward;
- mesma `wallet_forward_run`;
- janela móvel de 300 segundos;
- threshold de 2 wallets únicas;
- cooldown de 1.800 segundos por token;
- ordenação causal por `observed_at`, não por chain time retrospectivo.

Um evento só nasce quando o BUY atual faz a contagem de wallets únicas cruzar o threshold de `<2` para `>=2`.

Exemplo:

```text
A compra T às 10:00:00  -> 1 wallet
A compra T às 10:00:20  -> continua 1 wallet
B compra T às 10:01:10  -> 2 wallets -> CONVERGÊNCIA em 10:01:10
C compra T às 10:01:30  -> não cria novo evento do mesmo burst
```

A wallet B é o **trigger** porque a chegada dessa observação é o instante em que o sistema poderia saber que o threshold foi atingido.

## Causalidade

A regra usa `observed_at`. Isso é deliberado.

Se uma transação ocorreu on-chain às 10:00 mas nosso polling só a descobriu às 10:03, ela não pode ser usada para afirmar que havia confirmação às 10:00.

Cada evento persiste/expõe:

- token;
- instante causal do trigger;
- `trigger_event_id` e `trigger_observation_key`;
- wallet que fechou a convergência;
- wallets participantes;
- primeiro/último BUY observado dentro da janela;
- span da convergência;
- lag `chain_time -> observed_at` do BUY gatilho.

## Cooldown por token

Sem cooldown, um token muito ativo poderia sair e voltar da janela e gerar várias pseudo-amostras do mesmo episódio.

O cooldown de 30 minutos é somente uma regra de **amostragem do relatório**, não um cooldown de trading e não um filtro da Wave.

Ele pode ser alterado explicitamente no CLI para análise de sensibilidade, mas qualquer estudo econômico futuro deve pré-declarar o valor antes dos outcomes.

## Jupiter no instante de convergência

O BUY que fecha a convergência já é um evento do `wallet_quote_watch`. Portanto, quando a run possui Jupiter habilitado, o relatório consegue auditar as tentativas de quote ligadas ao **mesmo observation_key** do trigger.

Isso permite medir:

```text
2ª wallet observada
-> convergência detectável
-> +0/+15/+30/+60/+120s
-> route quote Jupiter do mesmo BUY trigger
```

Isso ainda não é fill. Quote-only continua proxy de rota/preço e transação candidata montada também não prova landing.

## CLI

Depois da run de Wallet Forward:

```powershell
python wallet_forward_convergence.py
```

Para uma run específica:

```powershell
python wallet_forward_convergence.py --run-key <RUN_KEY>
```

JSON auditável:

```powershell
python wallet_forward_convergence.py --json
```

Parâmetros de pesquisa:

```powershell
python wallet_forward_convergence.py `
  --window-seconds 300 `
  --min-wallets 2 `
  --token-cooldown-seconds 1800
```

## O que este relatório pode responder

- quantos BUYs a coorte realmente fez na run;
- em quantos tokens houve convergência observável;
- quanto tempo levou entre o primeiro BUY e o BUY que fechou a convergência;
- qual era o lag de detecção nesse trigger;
- se o Jupiter conseguiu fornecer route quote nos delays coletados para aquele trigger.

## O que ele NÃO pode responder

Ele não prova:

- que as wallets possuem edge;
- que duas wallets são melhores que uma;
- que a convergência prevê retorno;
- que o token deveria ser comprado;
- que a rota seria executada com aquele preço;
- que as wallets são independentes entre si;
- que não existe coordenação, funding comum ou relação entre elas.

## Relação com o placebo

Convergência é apenas a variável de exposição que queremos observar.

Para testar valor incremental, precisamos de controles. O desenho principal continua:

```text
target wallets pré-selecionadas
vs
placebo wallets pareadas por comportamento pré-período
```

A infraestrutura de `wallet_confirmation_study.py` existe para congelar grupos/policy antes dos outcomes. O universo local atual ainda é pequeno para um placebo econômico forte.

Também poderão existir controles temporais/comportamentais adicionais no futuro, mas eles não substituem o target-vs-placebo pré-período.

## Uso com a coleta de 6h de 2026-08-31

A coleta de 6h Wallet + Jupiter que já estava em execução quando este módulo foi adicionado **não precisa ser reiniciada**. O relatório é pós-processamento sobre as tabelas e run manifest que a coleta já grava.

Quando a execução terminar, basta puxar os commits novos e rodar o CLI. Se não houver convergência, `0 eventos` é um resultado válido de observabilidade, não uma falha do código.
