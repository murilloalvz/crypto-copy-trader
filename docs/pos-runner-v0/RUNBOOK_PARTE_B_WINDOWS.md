# RUNBOOK — Parte B ao vivo (Windows)

Cobre o bot ao vivo completo: **POS-RUNNER-V0** (congelado, pré-registrado) e **POS-RUNNER-V1** ("regras do
professor", PROMPT DEFINITIVO) rodando **no mesmo processo, sobre os mesmos candles**. PAPER / SOMENTE
LEITURA: sem chave privada, sem assinatura, sem ordem — o bot só lê dados públicos e manda alertas no
Telegram. Pressupõe os passos 1–6 do `README.md` já feitos (Python, `.env`, bot no @BotFather, `/start`).

## 1. Variáveis de ambiente (`signals_mvp\.env`)

Copie `signals_mvp\.env.example` para `signals_mvp\.env` e preencha — **nunca** cole um valor real num
chat, print ou log; o arquivo já está no `.gitignore` e o token nunca aparece no console/arquivo de log.

| variável | obrigatória? | para quê |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | sim | token do @BotFather |
| `TELEGRAM_CHAT_ID` | sim | seu chat id (@userinfobot) |
| `POS_RUNNER_RPC_URLS` | não (recomendada) | RPC Solana próprio (Helius/QuickNode); sem isto usa o RPC público, mais lento |
| `POS_RUNNER_SEM_V0` | não | qualquer valor não vazio desliga o V0 por completo (a V1 continua) — poupa orçamento de GT/RPC |

Nunca rode `type .env` nem cole o conteúdo do `.env` em lugar nenhum — se precisar confirmar que uma
variável está definida, use `Test-Path env:TELEGRAM_BOT_TOKEN` (só diz `True`/`False`, nunca o valor).

## 2. Testar a entrega antes de ligar pra valer

```powershell
cd C:\Users\LocalUser\Projetos\crypto-copy-trader
py -3 -m signals_mvp teste-pos-runner
```

Confirma token/chat id e o mini-gráfico do V0. A V1 usa o mesmo cliente de Telegram — se este teste chegou,
os alertas da V1 (ENTRADA/TP1/EXIT FULL/INVALIDADO/WATCHLIST/RESUMO) chegam do mesmo jeito.

## 3. Ligar / parar / retomar

```powershell
# ligar (1 comando; reinicia sozinho se cair)
signals_mvp\iniciar.bat
# (ou) py -3 -m signals_mvp iniciar

# parar com seguranca (grava os CSVs, fecha a sessao de uptime da V1)
signals_mvp\parar.bat
# (ou) py -3 -m signals_mvp parar
# (ou) Ctrl+C na janela do bot
```

**Retomar** é o mesmo comando de ligar — não existe passo separado. Ao religar, cada sinal (V0 e V1) é
reconstruído a partir dos candles já congelados no SQLite (`pr_bars`/`pr1_*`); nada é re-alertado nem
duplicado (chave `UNIQUE (chain, pool, tf, evento, ts_fechamento)` da V1, item 3.7). Um evento que deveria
ter acontecido enquanto o processo estava desligado/hibernando fica marcado `perdido_offline` em vez de
disparar um alerta atrasado.

## 4. Onde ficam os arquivos

Tudo dentro de `signals_mvp\dados\`:

| arquivo | o quê |
|---|---|
| `estado.sqlite` | fonte da verdade (V0 e V1); pode abrir com DB Browser for SQLite se quiser olhar direto |
| `pos_runner.csv` / `pos_runner_detalhe.csv` / `pos_runner_banca.csv` | contrato estável do V0 |
| `pos_runner_v1.csv` | um sinal por linha da V1 (gatilho, S/R/stop/TOPO, TP1, resultado, tags, hora BRT, origem) |
| `pos_runner_v1_filtrados.csv` | tudo que a V1 cortou sem alertar: `dado_invalido`, `filtrado_mc_baixo`, `filtrado_idade` |
| `pos_runner_v1_banca.csv` | gestão de banca da V1 (US$100 inicial, tamanho híbrido) |
| `heartbeat.json` | usado pelo supervisor para detectar travamento |

Logs em `signals_mvp\logs\signals_mvp.log` (secrets sempre mascarados).

## 5. Como ler o `pos_runner_v1.csv`

Colunas principais: `data`/`hora_brt` (fechamento do candle de decisão), `chain`, `token`, `contrato`,
`launchpad`, `tf`, `idade_h`, `janela_ouro` (`janela_ouro`/`fora_da_janela` — nunca filtra, só prioriza),
`topo`/`L_bc`/`queda_pct`/`S`/`R`/`n_wicks`, `gatilho` (um ou mais de `reacao_suporte`,
`power_candle_rompimento`, `rompimento_volume`), `entrada_mc`/`stop_mc`/`risco_pct`, `tp1_mc`/`exit_full_mc`,
`resultado_liq_pct`, `tempo_trade_h`, `motivo_saida`, `tags` (`risco_fora_da_faixa`, `HOLDER_CONCENTRADO`,
`holders_indisponivel`, `VAMP_RISK`), `holders_tag`, `mint_authority`/`freeze_authority`/`liquidez_usd`
(ainda `None` — reservado), `teste_vol_ratio`, `origem`, `versao_config_v1`, `perdido_offline`.

## 6. Evitar que o Windows suspenda o PC

`Configurações > Sistema > Energia e bateria > Tela e suspensão` → "Nunca" para "quando conectado". Se
usar notebook, marque também "A tampa fechada não faz nada" em `Configurações de energia adicionais` (senão
fechar a tampa pausa o processo mesmo sem suspender a tela).

## 6a. Heartbeat da V1

A cada 4h (`PosRunnerLive.heartbeat_interval_s`) a V1 manda uma mensagem "💓 POS-RUNNER-V1 ativo" no Telegram
com uptime, pools acompanhados, chamadas/min ao GeckoTerminal (média da janela) e os contadores
`dado_invalido`/`filtrado_mc_baixo` desde o heartbeat anterior — confirma que o processo está vivo sem
precisar abrir o console.

## 7. O que fazer em erro de rede/RPC

- **GeckoTerminal 429**: o bot já pausa e tenta de novo sozinho (`CallBudget`/`RateLimiter` compartilhados
  entre V0 e V1, orçamento único por ciclo); nada a fazer, exceto conferir se `POS_RUNNER_SEM_V0` ajudaria a
  liberar orçamento.
- **RPC "limite diário do plano"**: sai do rodízio por 1h sozinho e volta a tentar; o RPC público assume
  enquanto isso.
- **Erro de transporte (timeout/rede)**: log em `logs\signals_mvp.log`; o ciclo seguinte tenta de novo —
  nenhum pool é perdido (fica na fila/ativo, só atrasa).
- **`config.yaml` inválido depois de uma edição**: o bot avisa no console e mantém a versão anterior
  rodando até o arquivo ser corrigido (recarrega sozinho quando salvar de novo).

## O QUE O OPERADOR RODA

```powershell
cd C:\Users\LocalUser\Projetos\crypto-copy-trader
git pull
py -3 -m signals_mvp teste-pos-runner      # 1x, confirma a entrega antes de ligar
signals_mvp\iniciar.bat                    # liga (V0 + V1, PAPER/somente leitura)
# ... bot roda, alertas chegam no Telegram, CSVs em signals_mvp\dados\ ...
signals_mvp\parar.bat                      # para com seguranca quando quiser
```
