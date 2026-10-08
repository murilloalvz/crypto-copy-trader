# SIG-FAST-DISC-V0 — runbook de discovery (F7, 2026-10-08)

**Não rodar nada disto antes do sign-off** de
`docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md` (F5). Até lá,
o único comando autorizado nesta família de scripts é `--self-check` (dado
sintético, nenhum outcome real).

## Pré-condições antes de rodar pra valer

1. Sign-off do operador no pré-registro em lote (F5) — inclusive as 6
   perguntas abertas do fim daquele doc respondidas.
2. Decisão sobre o universo de sinais de cada família (H1: critério de
   seleção do cohort smart-money em holdout; H2: qual X minutos/grade de
   sobrevivência) — **isso ainda não está implementado**. O motivo é
   deliberado: construir esse loader antes do sign-off correria o risco de
   embutir uma decisão de design que o operador ainda não validou.
3. Cobertura de preço mínima confirmada via
   `benchmarks/sig_fast_v0/path_coverage_audit.py` (F1c) no banco real do
   operador — rodar isso primeiro, é só contagem, não gasta tentativa.
4. Branch `sig-fast-price-path-persistence-v0` com histórico suficiente
   capturado (as colunas novas de F1b só populam dali em diante — captura
   anterior a isso não tem preço derivável, confirmado em F1c contra o
   sandbox).

## Passo a passo (depois do sign-off)

1. **Construir o loader** (não existe ainda): um script que lê
   `market_trade_observations`/`market_lifecycle_observations` do banco real
   e produz uma lista de `DiscoverySignalInput` (ver
   `benchmarks/sig_fast_v0/discovery_v0.py`) — um por sinal de cada família,
   com o pool de baseline e os trades de cada candidato de baseline já
   carregados. Serializar como JSON (`asdict` de cada campo) pro
   `--input` do discovery engine.
2. **Hash antes de calcular, numa etapa separada e visível.** O próprio
   `run_discovery_v0` já escreve o manifesto de hash (`freeze_input_snapshot`)
   antes de computar qualquer métrica — mas o operador deve **commitar esse
   manifesto no git antes de olhar o `--output`**, não depois. Isso é o que
   torna o hash uma garantia real (congela a amostra antes de qualquer
   número ser visto), não só uma formalidade.
   ```bash
   git add sig_fast_disc_v0_manifest.json
   git commit -m "data: congela amostra SIG-FAST-DISC-V0 antes do calculo"
   ```
3. **Rodar o discovery**:
   ```bash
   python3 -m benchmarks.sig_fast_v0.discovery_v0 \
     --input <caminho do JSON montado no passo 1> \
     --manifest-output sig_fast_disc_v0_manifest.json \
     --output sig_fast_disc_v0_result.json \
     --stall-guard-seconds 300
   ```
   A saída vai só pro arquivo `sig_fast_disc_v0_result.json` — o script não
   imprime número econômico no terminal. Isso é deliberado: evita que um
   número apareça de relance no console antes do operador decidir se vai
   revisar com calma.
4. **Stall guard**: cada fase (congelar hash, varrer a grade) tem um timeout
   (`--stall-guard-seconds`, default 300s). Se estourar, o processo levanta
   `StallGuardTimeout` em vez de ficar pendurado indefinidamente — mesmo
   espírito do "stall guard" já usado no runbook do
   `bundle-bot-detection-v0-plumbing` (commit `0fd29e1`, "console-stall-safe
   runbook + port forward-collector stall guard").
5. **Ler o resultado depois, não durante.** Abrir
   `sig_fast_disc_v0_result.json` só depois do passo 2 (hash já commitado).
   O arquivo tem, por família e por Δ: a regra de saída escolhida no treino
   (70%), a média/PF líquidos no treino e no holdout (30%, com a MESMA regra,
   nunca reselecionada), e a taxa de P(+50% antes de −30% em 15min) do sinal
   vs. do baseline pareado, treino e holdout.
6. **Decidir o veredito seguindo F5, seção "PASS exige todos"** — sem
   reajustar nada depois de ver o número (regra 4 do pré-registro em lote).
7. **Atualizar o registro** (`docs/research-hypothesis-registry-v1-2026-10-04.md`)
   com o resultado, no mesmo commit, por família.

## O que este runbook NÃO cobre (ainda)

- O loader do passo 1 (depende das decisões de sign-off do F5).
- Qualquer execução real — nada neste commit rodou o discovery engine contra
  dado real; só `--self-check` foi executado, contra dado 100% sintético.
- A fonte de cotação SOL/USD pro tamanho de posição (pergunta aberta do F5).

## Auto-teste disponível agora

```bash
python3 -m benchmarks.sig_fast_v0.discovery_v0 --self-check
```

Roda o engine inteiro (hash, stall guard, split 70/30, seleção de saída,
baseline pareado) contra 6 sinais sintéticos. Não lê nem escreve no banco
real.
