# DexPaprika — fonte secundária de candles da POS-RUNNER-V1

PAPER / READ ONLY. Sem chave privada, sem assinatura de transação. Este documento separa o que foi
**confirmado ao vivo** (chamada real, sem chave, em 2026-10-26, contra `api.dexpaprika.com`) do que
**ainda é suposição** — e cada suposição vem com a escolha conservadora que o código faz por causa
dela.

## O que o DexPaprika É e NÃO é nesta integração

- **NÃO substitui o GeckoTerminal** na reconstrução do setup da V1 (zona, pico, consolidação). Um
  token de 5–7 dias pode ter o pico fora da janela de 7 dias que o plano gratuito do DexPaprika cobre
  — só o GT tem o histórico completo necessário para a detecção.
- **Usa-se só para duas coisas, as duas desligáveis independentemente do resto do bot:**
  1. **Fallback de atualização recente** — só quando o GeckoTerminal falhou de um jeito retomável
     (timeout, erro de rede, HTTP 5xx) ao buscar candles novos de um pool/tf já em acompanhamento.
     Nunca dispara na primeira carga de um pool (reconstrução do setup), só na atualização pontual.
  2. **Conferência cruzada, só log** — para uma amostra pequena (1 em cada N eventos WATCHLIST/
     ENTRADA, configurável) compara o candle que o GT já usou na decisão contra o mesmo candle do
     DexPaprika, campo a campo, e grava divergências além de uma tolerância configurável. **Nunca
     decide nada** — é só auditoria.

## Endpoint confirmado (chamada real, sem chave, 2026-10-26)

```
GET https://api.dexpaprika.com/networks/{network}/pools/{pool_address}/ohlcv
```

Parâmetros: `start` (obrigatório; timestamp Unix, RFC3339 ou relativo `-24h`/`-7d`), `end` (opcional),
`interval` (`1m|5m|10m|15m|30m|1h|6h|12h|24h`, default `24h`), `limit` (1–1000, default 10).

Resposta: lista JSON direta (sem envelope `data`, diferente do GeckoTerminal) de:

```json
{"time_open": "2026-10-25T19:00:00Z", "time_close": "2026-10-25T20:00:00Z",
 "open": 101.79, "high": 101.90, "low": 101.60, "close": 101.81, "volume": 1163685}
```

Chave (quando configurada) vai no header `Authorization`, **valor cru, sem prefixo `Bearer`**
(confirmado no SDK oficial da DexPaprika).

### Plano SEM chave ("keyless") — valores REAIS medidos, não os da documentação estática

A documentação de texto do DexPaprika cita "15 req/min" para o plano sem chave. **O valor real,
lido do header `ratelimit-limit` numa chamada ao vivo, é 10/min.** O código **nunca usa um número
fixo** para isto — `DexPaprikaHttp` lê `ratelimit-limit`/`ratelimit-remaining` e
`x-credits-limit`/`x-credits-remaining`/`x-credits-reset` de **toda resposta** (sucesso ou erro) e
usa esses valores reais, nunca uma suposição. Confirmado ao vivo: 10.000 créditos na janela móvel de
30 dias, `x-api-plan: keyless`.

Fora da janela permitida (intervalo `<1h` ou histórico além de 24h sem chave; além de 7 dias mesmo
com chave gratuita), a API devolve **HTTP 403** com corpo `{"error":"plan_required",...}` — o código
trata isto como `ApiError(kind="plan_limit")`: **nunca fatal**, nunca conta como falha de
disponibilidade no circuit breaker (é um limite esperado do plano, não uma instabilidade).

## O que NÃO foi confirmado — e a escolha conservadora de cada caso

| Suposição não confirmada | Risco se estiver errada | Escolha do código |
|---|---|---|
| Convenção de preço (`open/high/low/close`) do DexPaprika é a mesma do GeckoTerminal com `currency=token, side=base` (mesma ordem de tokens no par) | Um candle de fallback entraria no detector com uma escala de preço diferente da esperada | A conferência cruzada (item 2) é exatamente o mecanismo que valida isto na prática — divergências grandes e sistemáticas num token aparecem no CSV/tabela antes de confiar no fallback para aquele pool |
| Unidade do campo `volume` (visto na amostra real: números grandes como `1163685`, não claramente a mesma unidade do volume do GT) | `rompimento_volume` (gatilho que compara volume contra a média da caixa) poderia disparar errado com uma escala diferente | **O fallback NUNCA usa o volume do DexPaprika — grava sempre `0.0`.** Conservador: no máximo deixa de disparar `rompimento_volume` num candle de fallback; nunca dispara por engano com escala errada |
| Atraso real de indexação do candle no plano gratuito | Um candle "fechado" podia na verdade ainda estar sujeito a correção/reindexação | Atraso de segurança configurável (`DEXPAPRIKA_ATRASO_MIN_S`, padrão 120s): um candle só é aceito com pelo menos esse atraso desde o próprio fechamento; o atraso observado de cada candle aceito é registrado (`DexPaprikaProvider.atrasos_observados_s`) para o operador acompanhar |
| Host de planos pagos (`api-pro.dexpaprika.com`, citado no SDK oficial para contas Dev/Pro/Enterprise) | Uma chave paga podia precisar de outro host | Fora do escopo desta integração: o código sempre usa `https://api.dexpaprika.com` (o host que o operador confirmou), qualquer que seja o plano da chave. Documentado aqui para quem for revisar depois |

## Circuit breaker e orçamento de créditos

- **Circuit breaker** (`CircuitBreaker` em `signals_mvp/pos_runner/dexpaprika_v1.py`): depois de 3
  falhas SEGUIDAS de indisponibilidade real (timeout, erro de rede, HTTP 5xx, HTTP 429) — nunca
  `plan_limit` —, fica "aberto" por 5 minutos (padrão) e nenhuma chamada nova é tentada nesse
  intervalo, nem gasta crédito tentando. Fecha de novo automaticamente depois da pausa.
- **Orçamento de créditos**: antes de qualquer chamada nova, o código confere se os créditos já
  consumidos (lidos do header da ÚLTIMA resposta real, nunca um contador local reinventado)
  ultrapassaram `DEXPAPRIKA_CREDITOS_TETO_PCT` (padrão 80%) do limite do plano. Acima disso, o
  recurso fica "indisponível" até o próprio DexPaprika renovar a janela móvel de 30 dias.

## Impacto no orçamento de chamadas e de créditos

- **Fallback**: no máximo 1 chamada extra por pool/tf, só quando o GT já falhou naquele ciclo (nunca
  substitui a chamada do GT, é estritamente adicional nos ciclos de instabilidade).
- **Conferência cruzada**: 1 chamada extra em cada `DEXPAPRIKA_AMOSTRA_CADA_N` (padrão 5) eventos
  WATCHLIST/ENTRADA da V1 — não em todo sinal, por desenho (orçamento de créditos).
- Com o plano keyless (10.000 créditos/30 dias, ~10 req/min) isto sustenta uma operação pequena
  confortavelmente; para mais volume, uma chave gratuita (100.000 créditos, ~30 req/min, grátis em
  `https://console.dexpaprika.com`) dá bastante margem. `DEXPAPRIKA=0` desliga tudo isto por completo
  (zero chamada nova) sem precisar remover nenhum outro recurso do bot.
- **Fora de escopo nesta fase**: um HTTP 429 do *GeckoTerminal* já aciona o freio de orçamento do
  CICLO INTEIRO do POS-RUNNER (`RateLimited` propaga até `tick()`, que esgota o orçamento do ciclo) —
  o fallback do DexPaprika não tenta cobrir esse caso específico, para não arriscar o fluxo de
  orçamento compartilhado entre V0/V1/cotações. Ele cobre timeout/erro de rede/5xx por pool, que são
  as falhas mais comuns de um GT instável em produção.

## Colunas/tabelas novas (instrumentação — nunca mudam regra/decisão)

- `pr1_signals.fonte_candle` (`"gt"|"dexpaprika"`, padrão `"gt"`): de onde veio o ÚLTIMO candle que
  gerou a decisão daquele sinal.
- `pr_bars.fonte` (mesmo domínio): auditoria por candle; `pr_bars()` (lido pelo detector) continua
  selecionando só as 7 colunas de sempre — o detector nunca vê este campo.
- `pr1_dexpaprika_divergencias` / `pos_runner_v1_dexpaprika_divergencias.csv`: 1 linha por (candle,
  campo) divergente além da tolerância — `data, chain, token, contrato, tf, candle_ts, campo,
  valor_gt, valor_dexpaprika, diff_pct, versao_config_v1`.

## Variáveis de ambiente (todas em `.env`, nunca em log/commit)

| Variável | Padrão | O que faz |
|---|---|---|
| `DEXPAPRIKA` | `1` (ligado) | `0` desliga o recurso inteiro — zero chamada nova |
| `DEXPAPRIKA_API_KEY` | (vazia) | Opcional; vai só no header `Authorization`, nunca em log |
| `DEXPAPRIKA_REQ_POR_MIN` | `30` com chave / `10` sem chave | Teto do limitador próprio (nunca o do GT) |
| `DEXPAPRIKA_ATRASO_MIN_S` | `120` | Atraso mínimo exigido desde o fechamento do candle |
| `DEXPAPRIKA_CREDITOS_TETO_PCT` | `0.8` | Para de chamar acima desse % do limite de créditos |
| `DEXPAPRIKA_TOLERANCIA_PCT` | `1.0` | Tolerância (%) por campo na conferência cruzada |
| `DEXPAPRIKA_AMOSTRA_CADA_N` | `5` | Confere 1 em cada N eventos WATCHLIST/ENTRADA |

## O que o operador roda na VM

```bash
# no .env (nunca no git):
echo "DEXPAPRIKA_API_KEY=sua_chave_aqui" >> signals_mvp/.env   # opcional -- funciona sem chave tambem
git pull
tmux attach -t bot
# Ctrl+C para parar
./scripts/linux/iniciar.sh   # ou o comando que ja usa para subir de novo
```
