# Participant Quality Holdout V1 — o gate de profit factor foi artefato de outlier? (Fase A / A5) — 2026-10-04

Modo: PAPER / RESEARCH / READ ONLY. **Não reabre o KILL.** `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE` continua fechado; esta nota só avalia a confiabilidade do cálculo de profit factor, que também é usado pelo V68.

## Contexto

O KILL veio de um único gate entre seis: profit factor HIGH 0,443728 vs LOW 0,465290, com LOW n=17 (`docs/native-participant-quality-holdout-v1-result-2026-09-24.md`). Todas as outras métricas favoreciam HIGH (medianas, `mean_without_best`, taxa de perda catastrófica, Spearman +0,33).

## 1. O diagnóstico de outlier existe, mas não está no repositório

- O holdout calcula as métricas de cada grupo com `_group_metrics` → `_metrics_dict` (`benchmarks/burst_selection_diagnostic_v0/run.py:180`) → `robust_return_metrics_v47` (`src/route_research_feature_robustness_v47.py:23`). Esse objeto já inclui `largest_winner_share_gross_profit_pct` (participação do maior vencedor no lucro bruto, linhas ~55-58).
- O relatório completo é gravado em `artifacts/participant_quality_native_holdout_v1/<base>-report.json` (`participant_quality_native_holdout_v1.py`, linhas ~445 e ~603). A pasta `artifacts/` está no `.gitignore`, então o número está só na máquina do operador.
- O doc de resultado não copiou esse campo, e os números publicados não bastam para recuperá-lo: com PF e `mean_without_best` do LOW, a participação do maior vencedor fica em qualquer ponto entre 0% e 100% conforme o lucro bruto, que não foi publicado.

Leitura read-only que resolve a pergunta (rodar na máquina do operador, sem rede):

```powershell
python -c "import json,glob; p=sorted(glob.glob('artifacts/participant_quality_native_holdout_v1/*-report.json')); print(p); r=json.load(open(p[-1],encoding='utf-8')); print(json.dumps(r, indent=2)[:200])"
```

Depois localizar, para HIGH e LOW de H1, H2 e agregado, os campos `profit_factor`, `largest_winner_share_gross_profit_pct`, `mean_without_best_pct` e `count`. Critério de leitura proposto (descritivo, não muda o veredito): se no agregado o maior vencedor do LOW responde por mais de ~50% do lucro bruto do LOW, a vantagem de PF do LOW depende de um único episódio.

## 2. O V68 usa a mesma função de profit factor

- O gate primário do V68 calcula as métricas por grupo com `robust_return_metrics_v47` (`src/route_research_prospective_flow60_buy_share_v68.py:9` e `:89`) e exige `profit_factor > 1` do LOW em A, em B e no agregado (linhas ~158-164).
- É exatamente o cálculo usado no Participant Quality: PF ingênuo = soma dos ganhos / soma das perdas (`src/route_research_feature_robustness_v47.py:42-48`).
- Correção ao handoff (`docs/migration/HANDOFF_COPILOT_2026-10-04.md`): `src/route_research_evaluation.py::_metrics()` **não** é o PF do gate do V68. Ele só é usado na checagem de prontidão de cada subcohort (`_descriptive_readiness` em `src/signal_plane_forward_cohort_v0.py`), cujos números econômicos são descartados.

## 3. O que isso significa para o V68

O V68 não depende só do PF: o PASS também exige mediana do LOW > 0 em A e em B e `mean_without_best` agregado > 0, que são robustos a um único vencedor. Então um PF inflado por um outlier não basta para gerar PASS sozinho. O risco existe no sentido contrário (um FAIL decidido só pelo gate de PF com n pequeno), como aconteceu no Participant Quality. Nada disso muda o protocolo congelado; fica registrado para o relatório de robustez previsto na árvore de decisão do v68-09 (passo 1 do ramo PASS) e como pergunta de método para protocolos futuros, que é decisão do operador.
