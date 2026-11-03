# crypto-copy-trader

Pesquisa de sinais em memecoins da Solana, em modo **PAPER**: o bot só observa, decide e alerta —
nunca executa ordem, nunca assina transação, nunca guarda chave privada. Nenhum dinheiro real
passa por aqui.

> Projeto pessoal para portfólio, feito por [**Murillo Lourenço**](https://github.com/murilloalvz)
> — estudante de Análise e Desenvolvimento de Sistemas (FATEC Sorocaba), buscando estágio ou
> posição júnior em análise de dados/quant.

## ⚠️ Aviso de risco

Isto é um instrumento de **coleta e pesquisa**, não uma recomendação de investimento e não uma
prova de que qualquer estratégia aqui dá lucro. Nenhum número deste repositório — passado,
presente ou simulado — é uma promessa de retorno. Criptoativos, e memecoins em particular, são
extremamente arriscados; nada aqui deve ser copiado para operar dinheiro real sem validação
própria.

## O que tem aqui

O produto é `signals_mvp/`: um bot que acompanha pools recém-graduadas na Solana, filtra por
segurança (GoPlus) e qualidade de dado, aplica um detector de regras (duas versões, V0 e V1, cada
uma com sua config própria e seu próprio hash) e manda o alerta no Telegram — o operador decide e
executa manualmente no simulador. O bot também registra, para TODO sinal avaliado (enviado ou
não), o que teria acontecido depois, para medir com dado se a regra separa sinal bom de ruído.

## Honestidade metodológica (o diferencial deste projeto)

A parte que mais importa aqui não é o detector — é a disciplina em volta dele, porque é fácil
"descobrir" uma estratégia que só funcionou no passado por acaso:

- **Hipóteses pré-registradas**: antes de qualquer coleta que vai julgar uma regra, a regra fica
  **congelada por hash** e a decisão de validação é escrita ANTES de ver o resultado (ver
  `docs/pos-runner-v1/PROTOCOLO_VALIDACAO.md` e `docs/research-hypothesis-registry-v1-2026-10-04.md`).
- **Holdout selado**: a amostra que julga a hipótese do V0 foi fechada (hash do universo de pools)
  antes da descoberta rodar, para não vazar informação do futuro para o passado.
- **Config congelada com hash**: `versao_config`/`versao_config_v1` é um hash do YAML de regras.
  Mudar um parâmetro — mesmo um só — gera uma versão nova; estatísticas de versões diferentes
  nunca se misturam.
- **Versionamento sem misturar estatística**: cada linha gravada carrega a versão da config que a
  gerou; nenhum número é recalculado com uma regra que não existia quando o sinal saiu.
- **Resultados negativos documentados**: quando uma hipótese falha (ou um backtest é pausado por
  falta de amostra), isso fica registrado — não é escondido do histórico.

## Arquitetura

```
   Feeder                Scheduler              Detector             Notifier        Store
(GeckoTerminal/   -->   (ciclo, budget    -->   (regras V0/V1,  -->  (Telegram:  -->  (SQLite WAL
 GoPlus, com         de chamadas, backoff        gatilhos,            alerta +         + CSV de
 rate limit)         adaptativo)                 stop/TP)             botões +         formato
                                                                        resumo)         estável)
                                  ^
                                  |
                            ChainAdapter
                      (Solana ao vivo; BSC e
                       Robinhood Chain com
                      detecção de capacidade)
```

- **Feeder**: `geckoterminal.py`/`goplus.py` — clientes HTTP com limitador adaptativo (AIMD) e
  parsers testados contra respostas reais de API (não respostas inventadas à mão).
- **Scheduler**: `engine.py`/`worker.py`/`supervisor.py` — um ciclo por vez, com orçamento de
  chamadas por minuto e reinício automático se o processo cair.
- **Detector**: `triggers.py`/`scoring.py` + `pos_runner/` (as duas versões da estratégia
  "pos-runner", cada uma com sua config/hash próprios).
- **Notifier**: `telegram.py`/`alerts.py` — alerta, botões de feedback, resumo diário; nunca
  derruba o processo se o Telegram falhar.
- **Store**: `storage.py` — SQLite é a fonte da verdade (modo WAL); os CSVs são regenerados do
  banco de forma atômica, nunca escritos direto.
- **ChainAdapter**: `pos_runner/chain_adapter.py` — mesma lógica de regra em qualquer chain; cada
  chain declara sua própria capacidade (ex.: BSC/Robinhood Chain começam desligadas até terem
  dado real suficiente).

## Como rodar (Windows)

Passo a passo completo, copia-e-cola, em `signals_mvp/README.md`. Para a estratégia V1 ao vivo
("Parte B"), ver `docs/pos-runner-v0/RUNBOOK_PARTE_B_WINDOWS.md`. Resumo:

```
git clone <este repositório>
cd crypto-copy-trader
py -3 -m pip install -r signals_mvp\requirements.txt
copy signals_mvp\.env.example signals_mvp\.env   REM preencher TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
py -3 -m signals_mvp selfcheck                   REM testa tudo com dados falsos, sem rede
py -3 -m signals_mvp teste-rede                  REM confirma as APIs reais, só leitura
signals_mvp\iniciar.bat                          REM liga o bot (supervisor + worker)
```

## Stack e o que este projeto demonstra

- **Python** puro na parte que importa (biblioteca padrão + `requests`/`PyYAML`; sem framework
  pesado no bot).
- **SQLite em modo WAL** como fonte da verdade, com migração de esquema (`ALTER TABLE`
  idempotente) para não perder o banco do operador quando um campo novo é adicionado.
- **Cliente HTTP com rate limit adaptativo e backoff** contra uma API pública real (GeckoTerminal).
- **Mais de 440 testes automatizados** (`python -m unittest discover -s signals_mvp/tests`),
  incluindo testes de não-lookahead, idempotência em reinício, e um teste de equivalência que prova
  que uma mudança de instrumentação não altera nenhum sinal já gerado.
- **CI** (`.github/workflows/tests.yml`) rodando essa suíte a cada push/PR.
- **Estatística aplicada**: bootstrap em blocos, incerteza de edge via distribuição Beta,
  frequência via Poisson/binomial negativa — `signals_mvp/analise/simulacao_bloco.py` (ver
  `docs/pos-runner-v1/ANALISE_MONTE_CARLO.md`).

## Status atual e roadmap

- **V1 ("regras do professor")** está **ao vivo em modo paper**, config congelada no hash
  `279b79ffa3f0`. A validação formal (n=30, limite inferior de 90% da expectativa em R) está em
  coleta — ver `docs/pos-runner-v1/PROTOCOLO_VALIDACAO.md`.
- **V0** teve seu backtest (Parte A) pausado por falta de amostra numa das 24 combinações
  testadas; a combinação principal segue o rito de validação do registro de hipóteses.
- **Próximo passo**: Fase 2b (BSC) depois de confirmar capacidade real de dado na chain; nenhuma
  conclusão de edge antes de reunir as 30+ operações fechadas que o protocolo exige.

Nenhum destes itens é uma previsão de quando (ou se) uma estratégia vai "funcionar" — é só o que
está em andamento.

## Organização do repositório

```
signals_mvp/     o bot (único código ativo deste repositório)
docs/            documentação ativa (V0/V1, protocolo de validação, registro de hipóteses)
archive/         pesquisa anterior, pausada — ver archive/README.md e docs/LIMPEZA_MANIFESTO.md
```
