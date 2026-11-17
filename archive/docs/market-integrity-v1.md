# Market Integrity v1

## Status

**IMPLEMENTADO como camada observacional / RESEARCH ONLY.**

`Market Integrity v1` não altera `wave_v3_volume_integrity`, não cria um score de manipulação, não classifica um token como wash-traded e não produz decisão de compra/venda.

O objetivo é transformar campos agregados que já existiam nos snapshots causais em features de pesquisa explícitas, preservando o limite entre **sinal de alerta** e **prova de manipulação**.

## Por que existe

Volume alto, muitas transações ou forte pressão compradora podem representar demanda real, mas também podem coexistir com concentração, atividade coordenada, self-trading ou outras formas de volume pouco informativo.

O projeto já possuía alguns hard gates de risco/concentração no Wave. A nova camada não cria novos thresholds. Ela organiza o que podemos observar hoje e deixa explícito o que ainda não conseguimos observar.

## Implementação

Arquivos:

- `src/market_integrity.py`;
- `market_integrity_lab.py`;
- `tests/test_market_integrity.py`.

Método versionado:

```text
market_integrity_v1_aggregate_observational
```

## Features atuais

A partir de um `WaveTokenSnapshot` causal são calculados:

- buy pressure (%);
- desequilíbrio absoluto buys x sells (%);
- aceleração de volume contra a média de 5 minutos da última hora;
- parcela do volume de 5m dentro do volume de 1h;
- parcela do volume de 1h dentro do volume de 24h;
- transações por holder, quando o denominador existe;
- top10, dev, insiders e snipers;
- Risk Score da fonte;
- LP burn informado pela fonte.

As razões de volume são features cruas. Não existe threshold novo do tipo "acima de X é manipulação".

## Existing gate flags

Quando o snapshot cruza um threshold **que já pertence à política congelada do Wave**, o módulo pode repetir esse fato em `existing_gate_flags`, por exemplo:

- `trade_imbalance_extreme`;
- `top10_concentration_high`;
- `developer_concentration_high`;
- `insider_concentration_high`;
- `sniper_concentration_high`;
- `lp_burn_unconfirmed`.

Isso não é um segundo filtro. É apenas uma forma de tornar o contexto do snapshot pesquisável.

## Data quality flags

O módulo também deixa lacunas explícitas:

- `volume_windows_inconsistent`;
- `trade_counts_unavailable`;
- `one_sided_trade_counts`;
- `holders_unavailable`;
- `risk_unavailable`;
- campos de concentração indisponíveis.

Nenhuma lacuna é preenchida por inferência silenciosa.

## O que NÃO conseguimos detectar com esses dados

Todo resultado carrega limitações fixas:

- `aggregate_snapshot_cannot_identify_self_trading`;
- `counterparty_graph_unavailable`;
- `order_level_sequence_unavailable`;
- `funding_relationships_unavailable`.

Portanto, com o snapshot atual não é tecnicamente defensável afirmar que um token sofreu wash trading.

Para uma camada anti-manipulação mais forte será necessário coletar, quando viável:

1. transações/trades em granularidade mais fina;
2. wallets de contraparte ou participantes quando observáveis;
3. repetição temporal de pares de wallets;
4. padrões de ida-e-volta de capital;
5. concentração de volume por participante;
6. sequência de trades e tamanhos repetitivos;
7. relações de funding entre wallets;
8. comportamento cross-token das mesmas entidades.

Mesmo esses sinais devem começar como features, não como prova automática de fraude.

## CLI local

Sem rede:

```powershell
python market_integrity_lab.py
```

Por padrão ele lê os últimos sinais aceitos e as últimas rejeições causais existentes no SQLite.

Exemplos:

```powershell
python market_integrity_lab.py --signals 20 --rejections 20
python market_integrity_lab.py --signals 0 --rejections 50 --json
```

O CLI trabalha apenas sobre snapshots que já estavam persistidos naquele instante. Não consulta o estado atual do token para reescrever o passado.

## Como usar na pesquisa

Primeira aplicação correta:

```text
accepted/rejected snapshot
-> Market Integrity features
-> outcome futuro já observado
-> comparar distribuição
-> procurar padrões reproduzíveis
```

Exemplos de perguntas válidas:

- rallies perdidos pela Wave aparecem mais em qual faixa de concentração?
- crashes apresentam mais desequilíbrio buys/sells no snapshot inicial?
- ratios de volume muito concentrados em 5m distinguem vencedores de falsos breakouts?
- o efeito persiste depois de controlar liquidez, regime e missingness?

Pergunta inválida neste estágio:

> "este token está com wash trading?"

Os dados atuais não sustentam essa conclusão.

## Gate futuro

Uma feature de Market Integrity só poderá influenciar Strategy Router/entrada depois de:

1. ser definida antes do teste;
2. possuir cobertura suficiente;
3. mostrar relação prospectiva estável com outcomes;
4. sobreviver a controles/placebos e regimes diferentes;
5. não ser apenas uma duplicação de liquidez/volume/concentração já presente no Wave;
6. passar por shadow antes de qualquer capital real.
