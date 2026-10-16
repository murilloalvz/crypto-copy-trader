# Passo 0 do POS-RUNNER-V0 — versão 2 (regras do operador de 2026-10-16)

- `relatorio_passo0_v2.md` — o que o detector vê nos 5 exemplos com a config candidata a congelamento: fases detectadas
  (runner, fase 2, zona, testes de suporte, zona madura, entradas, invalidações) nos 3 timeframes, a medida da queda
  (extremos × corpos), a distorção da conversão para USD com cotação exótica e a idade nas entradas.
- `*_4h.png`, `*_1h.png`, `*_5m.png` — gráfico principal de cada exemplo (timeframe do professor quando informado), com
  as linhas de queda de 80% e 90% e 0,75 × L_bc.
- `*_1h_visao_geral.png` — histórico inteiro de cada exemplo no 1h, com as mesmas marcas.
- `fases.json` — todas as ondas, zonas e entradas detectadas (os números do relatório).

Calibração da DETECÇÃO, não avaliação: sem varredura de parâmetros e sem resultado de trade. Os 5 exemplos ficam fora de
todas as métricas do POS-RUNNER-V0. A versão 1 (proposta com varredura, 2026-10-15) continua em `../passo0_relatorio/`.

Mesmos candles da versão 1 (instantâneo `../passo0_relatorio/dados/ohlcv_cache_2026-10-15.tar.gz`, hash em
`../passo0_relatorio/dados/SHA256SUMS`). Reproduzir sem rede (mesmo texto e mesmo `fases.json`; só muda a linha da data):

```
mkdir -p /tmp/p0cache && tar xzf signals_mvp/pos_runner/passo0_relatorio/dados/ohlcv_cache_2026-10-15.tar.gz -C /tmp/p0cache
python -m signals_mvp.pos_runner.passo0 --cache /tmp/p0cache --out /tmp/p0v2 --fim 2026-10-15T17:00:00Z
```
