# Wallet Research Universe v1

Status: **IMPLEMENTADO / RESEARCH-READ ONLY**

## Por que esta etapa existe

O primeiro scan ampliado de Wallet Intelligence mostrou que o funil original de discovery era adequado para procurar wallets potencialmente copiáveis, mas era estreito demais para estudar estratégias de big wallets em geral.

No scan observado em 2026-08-30:

- 838 wallets chegaram ao funil;
- 637 foram eliminadas por ultrapassar 1000 trades em 30 dias;
- 188 falhas de dados foram registradas;
- apenas 1 wallet chegou ao Candidate Score;
- o deep dive dessa wallet falhou com HTTP 403 por créditos insuficientes.

A conclusão metodológica é que **estratégia de wallet** e **copyability direta** precisam ser pesquisadas em etapas separadas.

Uma wallet com 3000 trades/30d pode ser inviável para copiar transação por transação e, ainda assim, ser muito útil para descobrir um padrão de seleção, timing, escala de posição ou saída que possa ser abstraído e testado pelo CopyTrader.

## Separação de funis

### Funil de copyability existente

Permanece congelado. O limite de 1000 trades/30d continua sendo um gate válido para procurar wallets candidatas a cópia atrasada direta.

### Wallet Research Universe

O novo estágio é deliberadamente mais amplo e barato. Ele usa apenas snapshots de leaderboard para formar uma shortlist de pesquisa antes de solicitar `history` e `positions` individualmente.

Filtros amplos de qualidade:

- PnL realizado 30d positivo;
- ROI realizado positivo;
- pelo menos US$ 500 investidos;
- win rate >= 40%;
- pelo menos 5 tokens fechados;
- pelo menos 3 tokens negociados;
- pelo menos 3 dias ativos;
- último trade em até 7 dias;
- PnL strict.

**Frequência não elimina a wallet nesta etapa.** Ela apenas define um arquétipo operacional:

- moderate: até 300 trades/30d;
- active: 301–1000;
- high_frequency: 1001–3000;
- ultra_high_frequency: acima de 3000.

A shortlist usa round-robin entre essas faixas para impedir que um único estilo domine a amostra de pesquisa.

## Disciplina de créditos

`research_wallet_universe.py` não chama `wallet_history` nem `wallet_positions` por wallet.

Com `--per-view 100`, são usadas cinco visões do leaderboard e, em condições normais, uma página por visão. O objetivo é gastar poucas chamadas para selecionar endereços antes do enriquecimento caro.

Depois da shortlist, aprofundar apenas algumas wallets com:

```powershell
python wallet_intelligence.py <ADDRESS> --positions 100
```

A sincronização on-chain é separada e opcional:

```powershell
python wallet_intelligence.py <ADDRESS> --positions 100 --sync-onchain
```

## Regra de interpretação

Uma wallet high-frequency pode entrar no universo de **pesquisa**, mas não fica automaticamente apta a copy trading. O objetivo é descobrir se existe uma estratégia subjacente reproduzível com atraso e custos realistas.

A `wave_v3_volume_integrity`, seus filtros e o `exit_engine_v1` não são alterados por esta etapa.
