# External Evidence Reuse Map v1

## Objetivo

Usar pesquisa pública para reduzir busca cega sem transformar literatura, datasets ou relatos de traders em uma estratégia pronta.

Regra central:

```text
Evidência externa -> prior/hipótese -> teste causal nosso -> decisão
```

Nunca:

```text
artigo/leaderboard -> regra de compra automática
```

## Níveis de reaproveitamento

- **ALTO**: desenho experimental, dataset público, técnicas de controle de viés e métricas.
- **MÉDIO**: feature ou mecanismo plausível que ainda precisa ser validado no nosso universo.
- **BAIXO**: regra de trading, threshold ou relato de trader sem validação independente.

## Mapa

### 1. RED-REJECT-2026-v1 / Post-Rejection Follow-up Sampling

Fontes:

- https://zenodo.org/records/21402477
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7129798

Evidência pública relevante:

- 96 dias contínuos;
- 4.635 tokens únicos;
- 716.762 observações pós-rejeição;
- preço, liquidez, volume, mudanças temporais, venue e tempo desde a rejeição;
- licença do dataset CC-BY-4.0;
- disclosure de pedidos de patente sobre metodologias específicas de DEX/trading.

**Reaproveitamento: ALTO para metodologia e benchmark; BAIXO para copiar filtros específicos.**

Uso no CopyTrader:

- `Rejection Intelligence v1`;
- persistir decisão e snapshot causal;
- acompanhar rejeições em horizontes futuros;
- medir false negatives, crashes evitados e missingness;
- manter filtros atuais congelados enquanto coletamos evidência.

Não fazer:

- copiar thresholds ou detectores específicos do corpus;
- afirmar que a população daquele dataset é igual à nossa;
- ignorar disclosure de propriedade intelectual.

### 2. Coordinated Sniper Cohorts / RED-COHORT-2026-v1

Fonte:

- https://arxiv.org/abs/2607.02795

Evidência pública relevante:

- 1.578.333 observações de compradores;
- 166.098 launches;
- 1.012 coortes persistentes identificadas;
- launches tocados por coortes tiveram maior buyer flow/inflow;
- porém placebo de wallets pareadas por atividade apresentou lift ainda maior, enfraquecendo interpretação causal simples.

`Placebo` = grupo de comparação construído para testar se o efeito atribuído ao sinal também aparece sem aquele sinal específico.

**Reaproveitamento: ALTO para controles/placebos; MÉDIO para hipótese de wallet co-occurrence.**

Uso no CopyTrader:

- nunca tratar duas ou mais wallets entrando juntas como prova automática de edge;
- comparar confirmação por wallets contra controles pareados por atividade/frequência;
- exigir que Wallet Confirmation acrescente informação além de simplesmente escolher tokens já populares.

### 3. Pump.fun graduation prediction

Fonte:

- https://arxiv.org/abs/2602.14860

Evidência pública relevante:

- características estruturais e comportamentais durante a bonding curve melhoram a previsão de graduação quando condicionadas ao estado da curva.

`Bonding curve` = mecanismo de preço/liquidez usado na fase inicial de um token no Pump.fun antes de ele migrar para negociação posterior.

`Graduação` = atingir a condição de saída dessa fase inicial. Graduação **não é sinônimo de lucro de trading**.

**Reaproveitamento: MÉDIO para features; BAIXO para transferir o target diretamente.**

Uso no CopyTrader:

- considerar idade, estágio do launch e contexto estrutural como features futuras;
- separar estratégia pre-graduation de estratégia pós-graduation;
- não usar probabilidade de graduação como proxy automático de retorno líquido.

### 4. Graduation regime / social presence

Fonte:

- https://arxiv.org/abs/2607.02823

Evidência pública relevante:

- análise de centenas de milhares de launches;
- forte associação entre presença de canais sociais e graduação no período analisado;
- forte mudança de taxa-base entre regimes temporais.

**Reaproveitamento: MÉDIO.**

Uso no CopyTrader:

- Social Intelligence deve medir presença, timing e atividade social como contexto;
- sempre controlar por regime/idade/estágio;
- social é feature, não oracle;
- evitar modelo que aprenda apenas uma taxa-base antiga.

### 5. A Midsummer Meme's Dream — USENIX Security 2026

Fonte:

- https://www.usenix.org/conference/usenixsecurity26/presentation/mongardini

Evidência pública relevante:

- 34.988 memecoins em quatro chains;
- estudo longitudinal de três meses;
- entre tokens de alto retorno (>100%), 82,89% apresentaram evidência de mecanismos de crescimento artificial segundo os detectores do estudo;
- wash trading e Liquidity Pool-Based Price Inflation (LPI) aparecem como mecanismos importantes;
- manipulações iniciais frequentemente antecederam pump-and-dump/rug-pull na amostra estudada.

`Wash trading` = negociações artificiais, muitas vezes entre entidades relacionadas, usadas para criar aparência de atividade/volume.

`LPI` = inflação de preço baseada na estrutura da pool, em que compras estrategicamente pequenas podem produzir grande aumento aparente quando a liquidez é rasa.

**Reaproveitamento: ALTO como prior de risco; MÉDIO para features específicas.**

Uso no CopyTrader:

- volume alto não pode ser interpretado isoladamente como demanda orgânica;
- concentração, liquidez, fluxo, wallets relacionadas e forma do volume merecem features anti-manipulação;
- Wave Score deve continuar sendo radar, não evidência suficiente de edge.

### 6. Heavy tails e dependência de outliers

Evidência externa já revisada no market-research baseline mostra exemplos de paper trading em que poucos grandes vencedores carregam o resultado e a remoção dos maiores winners muda a conclusão.

`Heavy tail` = distribuição em que movimentos extremos ocorrem com frequência suficiente para dominar médias e PnL agregado.

**Reaproveitamento: ALTO para metodologia.**

Uso no CopyTrader:

Sempre reportar, quando a amostra permitir:

- média e mediana;
- Profit Factor;
- drawdown;
- best/worst;
- resultado sem maior vencedor;
- resultado sem top N;
- participação do maior vencedor no lucro bruto;
- cobertura e missingness.

### 7. Listas públicas de traders lucrativos

Relatos e levantamentos secundários sugerem forte heterogeneidade de holding time e estilo entre traders lucrativos.

**Reaproveitamento: BAIXO como evidência de edge; MÉDIO para gerar arquétipos de pesquisa.**

Uso no CopyTrader:

- procurar múltiplos arquétipos;
- não copiar thresholds relatados;
- verificar wallets on-chain;
- medir se o comportamento sobrevive à nossa latência e custo.

## Separação por lifecycle

Uma fonte pode estudar a fase de bonding curve e outra estudar pools pós-graduação. Misturar as duas populações gera conclusões erradas.

Antes de reutilizar qualquer evidência, registrar:

- chain;
- venue;
- fase do token;
- janela temporal;
- target original do estudo;
- custos considerados;
- tipo de dado: histórico, paper, forward ou execução real.

Essa regra é especialmente importante para comparar estudos de sniper/pre-graduation com nossa Wave, que normalmente observa mercados já negociáveis e com filtros de liquidez.

## Fila de testes derivada desta pesquisa

Prioridade alta:

1. Wallet latency + Jupiter causal route quotes — já EM TESTE.
2. Rejection Intelligence — IMPLEMENTADO, aguardando novas discoveries para formar amostra.
3. Wallet archetype causal replay com custos.
4. Outlier/missingness stress padronizado para qualquer estratégia candidata.

Prioridade média:

5. Wallet Confirmation com controles/placebos de atividade.
6. Organic-flow / manipulation features: distinguir volume útil de atividade potencialmente artificial.
7. Social incremental-value test: medir o que social acrescenta depois de controlar por Wave/Wallet/contexto.

Prioridade posterior:

8. Strategy Router somente após pelo menos dois arquétipos passarem por evidência forward suficiente.
9. Machine learning apenas quando houver dataset causal limpo e target definido; não usar ML para compensar falta de hipótese/dados.

## Regra de promoção

Nenhuma hipótese externa muda a estratégia diretamente. A promoção continua:

```text
prior externo
-> hipótese explícita
-> dados nossos causalmente válidos
-> replay com custos
-> stress/outlier/missingness
-> shadow forward
-> somente depois integração
```

## Revisão

Este mapa é um documento vivo de pesquisa. Novas fontes podem aumentar ou reduzir confiança em uma hipótese, mas alterações nos gates da estratégia exigem experimento separado e pré-declarado.
