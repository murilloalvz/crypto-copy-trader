# Rodada 16 — Parte F: Operação e Robustez (auditoria read-only)

PAPER/READ-ONLY. Nenhum código/config/parâmetro/detector/hash tocado. Não existe banco ao vivo da VM
neste checkout (gitignored, nunca commitado) — uso real de RAM/CPU na VM de produção **não é
medível** desta sessão; os achados abaixo vêm de leitura de código (fatos verificados) e, onde
indicado, de inferência sobre o que esse código implica numa VM de 1GB (hipótese, marcada como tal).

**Resumo**: o mecanismo de restart/retomada é sólido e testado (sinal aberto nunca se perde,
alerta nunca duplica — ambos verificados no código e em teste real). O ponto mais sério é um
crescimento de memória não limitado: listas `bars`/`tr`/`events` de cada `DetectorV1` nunca são
truncadas, e os detectores da V3 especificamente **nunca são liberados** quando um pool é
aposentado/rotacionado — isso soma a outros caches sem limite de vida (autoridade de mint, sets de
"já visto"). Não há trava contra dois processos do bot rodando ao mesmo tempo contra o mesmo banco
(mitigado parcialmente pela unicidade de `pr_alert_once`, mas não pelo orçamento de API/RPC, que
dobraria silenciosamente). systemd tem `Restart=always` mas sem `MemoryMax=` nem proteção de
crash-loop reforçada — right now o dead-man's-switch (healthchecks.io) está implementado
corretamente (ping "ok" só depois do ciclo completar; "fail" em exceção), então um crash real seria
detectado, mas um vazamento de memória lento seria apenas um OOM-kill eventual do kernel, sem aviso
prévio.

## Achados

### [P1] `dets_v3` nunca é liberado quando um pool é aposentado/rotacionado — vazamento de memória específico da V3
- **Evidência**: `signals_mvp/pos_runner/live.py:1098-1107` (função de aposentação por estagnação) e
  `signals_mvp/pos_runner/live.py:1212-1221` (rotação pra `dormente`) ambas fazem
  `self.dets.pop(...)`, `self.dets_fecham.pop(...)`, `self.dets_v1.pop(...)`,
  `self.dets_v2.pop(...)`, `self.dets_sombra_mc.pop(...)`, `self.dets_sombra_queda96.pop(...)`,
  `self.dets_sombra_base4.pop(...)`, `self.dets_radar.pop(...)`, `self.sched.pop(...)` — mas em
  NENHUM dos dois lugares aparece `self.dets_v3.pop(...)`. Confirmado por `grep -n "dets_v3"
  signals_mvp/pos_runner/live.py` — o único método de criação é `_detector_v3` (via
  `setdefault`-style lazy init), zero `.pop`/`del self.dets_v3` em todo o arquivo.
- **Impacto nas conclusões**: nenhum impacto direto em R/estatística (é um objeto em memória, não um
  dado que entra em cálculo). Impacto é **operacional**: cada pool que a V3 já rastreou alguma vez
  mantém seu(s) `DetectorV1` (um por `(pool, tf)`) vivo pra sempre no processo, mesmo depois do pool
  virar `dormente`/`encerrado` — nunca liberado até o processo reiniciar.
- **Correção proposta**: adicionar `self.dets_v3.pop((pool, tf), None)` (e, se existirem,
  `self._v3_suspeito.pop`/outros dicts por-pool da V3) nos dois pontos de rotação/aposentação, MESMO
  padrão das outras versões.
- **Toca hash/exige restart?**: não toca hash (zero mudança em detector/params/critério — é limpeza
  de estado em memória, fora do que qualquer hash cobre). Exigiria restart do processo pra entrar em
  vigor (mudança de código).
- **Confiança**: alto — leitura direta do código, grep confirma a ausência em todo o arquivo.

### [P1] `DetectorV1.bars`/`.tr`/`.events` crescem sem limite pela vida do pool rastreado
- **Evidência**: `signals_mvp/pos_runner/detector_v1.py:61-63` (`self.bars: list[Bar] = []`,
  `self.tr: list[float] = []`, `self.events: list[EventV1] = []`) e `update()` (linha ~135-141)
  só faz `self.bars.append(bar)`/`self.tr.append(...)` — nenhum `del`/slice/janela deslizante em
  nenhum lugar do arquivo (`grep -n "self.bars\[" signals_mvp/pos_runner/detector_v1.py` só mostra
  leituras por índice, nunca truncamento).
- **Impacto nas conclusões**: nenhum em R/estatística. Operacional: cada `(pool, tf)` rastreado por
  V1 **e** V2 **e** V3 (3 instâncias de `DetectorV1`, mais `dets`/`dets_fecham`/sombras/radar — até
  ~8 instâncias por `(pool, tf)` em alguns casos) acumula a série COMPLETA de candles e eventos pela
  vida do rastreamento. Combinado com o achado anterior (V3 nunca libera ao rotacionar), o pior caso
  é um processo de longa duração numa VM de 1GB acumulando centenas/milhares de séries completas.
- **Correção proposta**: não é urgente mudar a lógica causal (o detector PRECISA de `bars`/`tr`
  passados pra calcular ATR/fases — truncar ingenuamente quebraria isso); a correção mais segura é
  garantir que a liberação no rotation (achado acima) realmente acontece pra TODAS as versões, e
  medir o consumo real de RAM na VM (não verificável daqui) antes de decidir se precisa também de
  uma janela deslizante no próprio detector.
- **Toca hash/exige restart?**: não toca hash. Qualquer mudança na estrutura do detector exigiria
  revisão cuidadosa (é código congelado por hash — mudar a classe, mesmo só por memória, teria que
  provar bit-a-bit que o comportamento não muda).
- **Confiança**: alto (crescimento sem limite é fato verificado); **hipótese** não verificada aqui é
  se isso já causou algum incidente real na VM — não há dado desta sessão para confirmar.

### [P1] Nenhuma trava contra dois processos do bot rodando ao mesmo tempo contra o mesmo banco
- **Evidência**: `signals_mvp/storage.py:590-592` configura `PRAGMA journal_mode=WAL` +
  `PRAGMA busy_timeout=30000` — protege contra corrupção do SQLite (WAL permite múltiplos
  leitores/1 escritor com espera), mas não existe PID file/`flock`/lock de aplicação em
  `storage.py`/`worker.py`/`supervisor.py` (`grep -n "flock\|FileLock\|pidfile" signals_mvp/*.py`
  não retorna nada). `docs/DEPLOY_VPS_LINUX.md` não tem nenhuma seção avisando o operador a conferir
  que não há 2 processos rodando antes de iniciar um novo (`grep -n "dois processos\|ja esta
  rodando"` não encontra nada).
- **Impacto nas conclusões**: não corrompe o banco (SQLite/WAL cobre isso) nem duplica alertas Telegram
  reais (`pr_alert_once` é `INSERT OR IGNORE` numa chave `UNIQUE`, protegido no nível do banco). O
  risco real é **dobrar silenciosamente o consumo de orçamento de API/RPC** (dois processos
  descobrindo/rastreando os mesmos pools, cada um gastando sua própria cota) — relevante logo depois
  de um restart manual (Rodada 15 pediu exatamente isso) se o processo antigo (ex.: sessão `tmux`
  esquecida) não for confirmado morto antes de iniciar o `systemd`.
- **Correção proposta**: adicionar um lock de arquivo simples (ex.: `fcntl.flock` num arquivo
  `.pid`/`.lock` dentro de `dados/`) no startup do `worker.py`, falhando alto e claro se já existir
  um lock ativo; documentar explicitamente no runbook de restart (`DEPLOY_VPS_LINUX.md` e o aviso da
  Rodada 15) o comando pra confirmar que não há processo duplicado (`pgrep -fa "signals_mvp"`) antes
  de reiniciar.
- **Toca hash/exige restart?**: não toca hash. Exige restart pra qualquer mudança de código.
- **Confiança**: alto — ausência confirmada por grep; CLAUDE.md raiz já reconhece esse invariante
  como importante ("one physical SQLite writer remains authoritative unless equivalence is proven"),
  mas nenhum mecanismo automático o impõe hoje.

### [P2] systemd sem `MemoryMax=` e sem proteção reforçada de crash-loop
- **Evidência**: `signals_mvp/scripts/linux/signals-mvp.service` tem `Restart=always` +
  `RestartSec=10`, mas nenhum `MemoryMax=`/`MemoryHigh=` e nenhum `StartLimitIntervalSec=`/
  `StartLimitBurst=` customizado. Com `RestartSec=10` e os defaults do systemd
  (`StartLimitIntervalSec` default 10s, `StartLimitBurst` default 5), um processo que crasha a cada
  10s levaria ~50s pra acumular 5 reinícios — MAIS que a janela padrão de 10s — então o limite padrão
  de burst **nunca dispara** nesse ritmo, e o serviço fica reiniciando indefinidamente sem nunca ser
  marcado `failed` (sem alerta via `systemctl status`/journal sozinho).
- **Impacto nas conclusões**: nenhum em R/estatística. Operacional: combinado com o achado de
  memória (acima), se o processo crescer até o kernel matá-lo por OOM, o ciclo
  crash→restart→crescer→crash se repete silenciosamente — o `healthchecks.io` (ping "fail"/ausência
  de ping) ainda pegaria isso no agregado (não é um falso-positivo de saúde — verificado: o ping
  "ok" só é enviado DEPOIS do ciclo completar com sucesso, `worker.py:504-517`), mas o operador só
  saberia "algo está errado", não a causa.
- **Correção proposta**: adicionar `MemoryMax=800M` (ou valor com folga sob o 1GB real) pra o systemd
  reiniciar de forma controlada antes do OOM-killer do kernel agir, e `StartLimitIntervalSec=600`/
  `StartLimitBurst=5` pra realmente marcar `failed` (e permitir um alerta externo) se crashar
  repetidamente num curto período.
- **Toca hash/exige restart?**: não toca hash nem código Python — é config de systemd, exige
  reinício do serviço (não do processo via `kill`/restart normal, mas `daemon-reload` + restart).
- **Confiança**: médio — a mecânica do systemd (burst window) é fato verificável de documentação
  pública do systemd, não testável nesta sessão (não há systemd aqui); o `.service` real na VM pode
  ter sido ajustado localmente de forma diferente do que está commitado — não verificável daqui.

### [P2] Teste `test_never_writes_to_the_database` só confere 1 de ~20+ tabelas
- **Evidência**: `signals_mvp/tests/test_saude.py:44-54` — o teste roda `saude.executar(...)` e só
  compara `SELECT * FROM pr1_signals` antes/depois. Não confere `pr2_signals`, `pr3_signals`,
  `pr_pools`, `meta`, `pr_carteiras_snapshot`, `pr_api_uso`, etc. O NOME do teste promete "nunca
  escreve no banco" (afirmação geral), mas a verificação cobre só uma tabela.
- **Impacto nas conclusões**: nenhum em R/estatística — é confiança no próprio processo de auditoria
  (`saude.py` roda, por design, contra o banco AO VIVO enquanto o bot está rodando; se algum dia
  ganhar uma escrita acidental numa tabela que não seja `pr1_signals`, este teste passaria mesmo
  assim).
- **Correção proposta**: trocar a comparação por um dump genérico de TODAS as tabelas (`sqlite_master`
  → `SELECT * FROM <tabela>` em loop) antes/depois, ou abrir a conexão do `saude.py` em modo
  `PRAGMA query_only=1`/read-only de fato (reforço estrutural, não só um teste que pode ficar
  desatualizado conforme tabelas novas são adicionadas — como `pr3_carteiras_sinal`, Rodada 15, que
  também não está coberta aqui).
- **Toca hash/exige restart?**: não.
- **Confiança**: alto — leitura direta do teste; é uma lacuna de cobertura real, não uma suposição.

### [P2] Sem teste/procedimento documentado de restauração do backup
- **Evidência**: `signals_mvp/backup.py` (toda a implementação) e `grep -rn "restaura\|restore"
  docs/*.md signals_mvp/tests/*.py` não encontram nenhum teste de restauração nem runbook de "como
  restaurar a partir de um backup". O backup em si está bem implementado (`backup_to` via API nativa
  do SQLite, consistente mesmo em WAL — `backup.py:1-5` docstring confirma e o código usa
  `sqlite3.Connection.backup`, nunca cópia crua de arquivo).
- **Impacto nas conclusões**: nenhum em R/estatística. Risco operacional: o mecanismo de backup nunca
  foi exercitado "pra valer" (restaurar e confirmar que o bot sobe normalmente a partir dele) — um
  backup que nunca foi restaurado é um backup não comprovado.
- **Correção proposta**: documentar (e, melhor, testar 1x manualmente na VM) o procedimento de
  restauração: copiar `estado-<ts>.sqlite` sobre o banco ativo com o serviço parado, reiniciar,
  confirmar `saude.py` reporta estado consistente.
- **Toca hash/exige restart?**: não (é só documentação/procedimento).
- **Confiança**: alto quanto à ausência de documentação/teste; não verificável se o operador já fez
  isso manualmente fora deste repositório.

## O que foi verificado como correto (sem achado, citado por transparência)
- Restart nunca perde sinal aberto nem duplica alerta: `pr_alert_once` é `INSERT OR IGNORE` sobre
  chave `UNIQUE` persistida no SQLite (`storage.py:1176-1180`), e `_startup` (`live.py:866-935`)
  reconstrói detectores a partir de `pr_bars` congelados para TODAS as versões (V1/V2/V3) de forma
  simétrica. Teste real cobrindo o cenário genuíno de retomada após lacuna:
  `test_pos_runner_v1_live.py:154` (`test_retomada_after_a_long_offline_gap_resumes_tracking...`).
- Dead-man's-switch (`healthchecks.io`) não tem o falso-positivo clássico de "ping antes de rodar o
  trabalho de verdade": `worker.py:502-517` só manda `"ok"` DEPOIS de `engine.run_cycle()` retornar
  sem excesão; exceção manda `"fail"`; um travamento real (sem exceção, sem retorno) simplesmente não
  manda ping nenhum — o próprio healthchecks.io detecta a ausência pelo timeout configurado.
- Backup usa a API nativa de backup do SQLite (seguro mesmo em WAL com escrita concorrente), nunca
  cópia de arquivo cru; retenção só apaga backups antigos DEPOIS de confirmar que o novo terminou.
- `util.redact` (`signals_mvp/util.py:152-162`) tem regex específico para token do Telegram
  (`\b\d{6,12}:[A-Za-z0-9_-]{30,}\b`) e para a URL `/bot<token>/...`, aplicado via `setup_logging`
  (`worker.py:413`, passando `secrets=[token, healthchecks_url]`) — cobertura correta para os 2
  segredos que o projeto de fato usa (Telegram + healthchecks URL). Não vi nenhum valor de segredo
  impresso em nenhum arquivo deste checkout (grep por padrões de token/URL com credencial não
  retornou nada fora de `.gitignore`/exemplos com placeholder).

## O que NÃO foi possível verificar nesta sessão
- Uso real de RAM/swap da VM de produção (1GB) — nenhum dado de telemetria da VM está neste
  checkout; os achados de memória acima são sobre crescimento estrutural do código, não uma medição
  real de quantos MB isso representa hoje.
- Se o `.service` realmente instalado na VM é idêntico ao commitado em
  `signals_mvp/scripts/linux/signals-mvp.service` (o operador pode ter ajustado localmente).
- Se já houve, na prática, um incidente de dois processos simultâneos ou um OOM real — não há log/
  histórico da VM disponível aqui.
- Se o backup já foi restaurado manualmente alguma vez fora deste repositório.
