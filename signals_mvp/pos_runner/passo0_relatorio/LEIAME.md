# Passo 0 do POS-RUNNER-V0 — evidência

- `relatorio_passo0.md` — relatório ao operador (resumo, gráficos, medidas, proposta, perguntas).
- `*_4h.png`, `*_1h.png`, `*_5m.png` — gráfico principal de cada exemplo (timeframe do professor quando informado).
- `*_1h_visao_geral.png` — histórico inteiro de cada exemplo no 1h, com todas as entradas da proposta numeradas.
- `medidas.json`, `varredura.json` — números do relatório e as 36 variantes da varredura.
- `dados/ohlcv_cache_2026-10-15.tar.gz` — instantâneo dos candles usados (cache do `OhlcvStore`: taxa em token de
  cotação, USD do GeckoTerminal para conferência e as séries de referência da cotação). Hashes em `dados/SHA256SUMS`.

Reproduzir sem rede (mesmo resultado):

```
mkdir -p /tmp/p0cache && tar xzf signals_mvp/pos_runner/passo0_relatorio/dados/ohlcv_cache_2026-10-15.tar.gz -C /tmp/p0cache
python -m signals_mvp.pos_runner.passo0 --cache /tmp/p0cache --out /tmp/p0rel --fim 2026-10-15T17:00:00Z
```

Os 5 exemplos são CALIBRAÇÃO: ficam fora de todas as métricas de resultado do POS-RUNNER-V0.
