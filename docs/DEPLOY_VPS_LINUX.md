# Deploy do bot numa VPS Linux (Oracle Linux 9)

Guia copia-e-cola para rodar o bot de sinais (PAPER / somente leitura) numa VM Oracle Linux 9
(1 GB de RAM + 2 GB de swap, x86_64), usando `tmux` para operar manualmente ou `systemd` para
ligar sozinho e sobreviver a reboot. Nenhum passo aqui depende de nada específico do Windows — o
mesmo código roda nos dois sistemas; só a forma de ligar/desligar muda.

> Em qualquer ponto: **não** rode nada daqui como `root`. Crie um usuário dedicado (passo 2).

## 1. Pacotes do sistema

```bash
sudo dnf install -y python3.11 python3.11-pip git tmux
python3.11 --version   # confirma 3.11+
```

## 2. Usuário dedicado (nunca root)

```bash
sudo useradd -r -m -d /opt/crypto-copy-trader -s /bin/bash signalsbot
sudo mkdir -p /opt/crypto-copy-trader
sudo chown signalsbot:signalsbot /opt/crypto-copy-trader
```

A partir daqui, troque para esse usuário (`sudo -iu signalsbot`) para clonar e rodar o bot — ele
nunca precisa de privilégio de root para nada.

## 3. Clonar e preparar o ambiente

```bash
sudo -iu signalsbot bash -lc '
  git clone <url-do-repositorio> /opt/crypto-copy-trader
  cd /opt/crypto-copy-trader
  python3.11 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
  cp signals_mvp/.env.example signals_mvp/.env
'
```

Edite `signals_mvp/.env` (formato `CHAVE=valor`, uma por linha — o mesmo arquivo serve tanto para
o bot quanto para o `systemd`, ver passo 5) e preencha pelo menos:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

**Nunca** rode `cat signals_mvp/.env` nem cole o conteúdo em lugar nenhum (chat, log, issue) — é
o único arquivo deste projeto que carrega segredo.

## 4. Testar antes de ligar de verdade

```bash
cd /opt/crypto-copy-trader
.venv/bin/python -m signals_mvp selfcheck      # testes + simulação com dados falsos, sem rede
.venv/bin/python -m signals_mvp teste-rede     # confirma as APIs reais, só leitura
.venv/bin/python -m signals_mvp teste-telegram # manda UMA mensagem de teste pro seu Telegram
```

## 5a. Rodar manualmente (tmux)

Útil para testar ao vivo antes de virar serviço, ou para operar sem `systemd`:

```bash
tmux new -s signals-mvp
cd /opt/crypto-copy-trader
./signals_mvp/scripts/linux/iniciar.sh
# Ctrl+B depois D para sair do tmux sem matar o bot (ele continua rodando dentro da sessão)
```

Para parar, numa sessão nova (ou dentro da mesma, se não tiver saído do `tmux`):

```bash
./signals_mvp/scripts/linux/parar.sh
```

Para voltar a ver o que o bot está fazendo: `tmux attach -t signals-mvp`.

## 5b. Rodar como serviço (systemd — recomendado para produção)

O arquivo `signals_mvp/scripts/linux/signals-mvp.service` já vem com `Restart=always` (reinicia
sozinho se cair), `EnvironmentFile` apontando para o `.env`, usuário não-root e desligamento
limpo via `SIGTERM`.

```bash
# edite User=, WorkingDirectory= e ExecStart= no arquivo se o caminho do clone for diferente
sudo cp signals_mvp/scripts/linux/signals-mvp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now signals-mvp
```

**Acompanhar os logs:**

```bash
sudo journalctl -u signals-mvp -f          # ao vivo
sudo journalctl -u signals-mvp -n 200      # últimas 200 linhas
```

Um conflito do Telegram (HTTP 409 — duas instâncias com o mesmo `TELEGRAM_BOT_TOKEN` fazendo
`getUpdates` ao mesmo tempo, por exemplo `systemd` ligado E uma sessão `tmux` manual ao mesmo
tempo) aparece claramente no log como `conflito 409: outra instancia deste bot...`. Se isso
acontecer, pare uma das duas (`parar.sh` na sessão manual, ou `systemctl stop signals-mvp`).

**Parar o serviço:**

```bash
sudo systemctl stop signals-mvp
```

**Atualizar o bot (git pull + reiniciar):**

```bash
sudo -iu signalsbot bash -lc '
  cd /opt/crypto-copy-trader
  git pull
  .venv/bin/pip install -r requirements.txt
'
sudo systemctl restart signals-mvp
```

**Desabilitar (não liga mais no boot, mas continua instalado):**

```bash
sudo systemctl disable signals-mvp
```

## 6. Trava de instância única

O bot nunca deixa duas instâncias escreverem no mesmo banco ao mesmo tempo: além do arquivo de
PID (`dados/supervisor.pid`, cross-plataforma), há um lock real de arquivo sobre o próprio banco
(`dados/estado.sqlite.lock`, via `flock` no Linux) — o sistema operacional libera esse lock
sozinho se o processo cair, nunca fica "travado" por engano. Se você tentar ligar uma segunda
instância, o comando recusa com uma mensagem clara em vez de corromper o estado.

## 7. Backup do banco

### Automatico (PEDIDO ADICIONAL FASE 6, item 1)

O bot já tira, sozinho, 1 backup por dia (checado a cada ciclo; dispara quando passar 24h desde o
último) usando a **API de backup nativa do SQLite** (`sqlite3.Connection.backup`, não uma cópia de
arquivo "crua" — funciona com o banco aberto e em modo WAL, sem travar nem arriscar pegar uma escrita
no meio). Os arquivos ficam em `signals_mvp/backups/` (fora de `dados/`, **nunca vai pro git** — já
está no `.gitignore`), nomeados `estado-<timestamp UTC>.sqlite`. Retenção configurável (padrão 7
dias — backups mais antigos são apagados automaticamente a cada rodada, só depois de confirmar que o
novo terminou sem erro):

```bash
# opcional no .env; sem isto o padrao (7 dias) ja vale
echo "BACKUP_RETENCAO_DIAS=7" >> signals_mvp/.env
```

Nada a fazer para ligar — é automático desde que o bot suba. Para confirmar que está rodando:

```bash
ls -la /opt/crypto-copy-trader/signals_mvp/backups/
```

### Baixar para o notebook

De qualquer backup (automático ou manual) para o seu notebook Windows, com o PowerShell (`scp` já vem
com o OpenSSH Client do Windows 10/11):

```powershell
scp signalsbot@<ip-da-vm>:/opt/crypto-copy-trader/signals_mvp/backups/estado-*.sqlite .
```

Ou, para sempre pegar só o mais recente:

```powershell
scp signalsbot@<ip-da-vm>:"$(ssh signalsbot@<ip-da-vm> 'ls -t /opt/crypto-copy-trader/signals_mvp/backups/estado-*.sqlite | head -1')" .
```

### Manual (copia direta do banco em uso, sem esperar o automatico)

O estado inteiro do bot (sinais, banca, feedback) fica em `signals_mvp/dados/estado.sqlite`. Para
copiar com o bot rodando (SQLite em modo WAL — seguro copiar os 3 arquivos juntos):

```bash
sudo -iu signalsbot bash -lc '
  cd /opt/crypto-copy-trader/signals_mvp/dados
  cp estado.sqlite estado.sqlite-wal estado.sqlite-shm /tmp/backup-$(date +%Y%m%d-%H%M)/ 2>/dev/null
'
```

(os sufixos `-wal`/`-shm` só existem enquanto o banco está em modo WAL com conexão aberta; copiar
sem eles também funciona, só perde as últimas escritas ainda não "commitadas" no arquivo
principal). Para um backup fora da VM, `scp` esses arquivos para o seu notebook periodicamente.

## 8. Swap (VM de 1 GB de RAM)

Se a VM ainda não tiver os 2 GB de swap:

```bash
sudo dnf install -y util-linux   # geralmente ja vem
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # confirma 2G de swap
```

## 9. SELinux e firewalld

- **SELinux**: deixe em modo `enforcing` (padrão do Oracle Linux 9) — o bot só faz chamadas HTTPS
  de saída e escreve dentro da própria pasta, nada que SELinux normalmente bloqueia. Se algo
  falhar de forma estranha, confira `sudo ausearch -m avc -ts recent` antes de pensar em
  desligar o SELinux (nunca desligue para "resolver" um problema sem confirmar que é SELinux).
- **firewalld**: **não abra nenhuma porta**. O bot só faz conexões de SAÍDA (GeckoTerminal,
  GoPlus, RPC Solana, API do Telegram) — nunca escuta nada. `sudo firewall-cmd --list-all` deve
  continuar sem nenhuma porta aberta para este serviço.

## 10. Monitoramento (dead man's switch — PEDIDO CONSOLIDADO FASE 3)

`Restart=always` do `systemd` cobre o processo cair e voltar sozinho — mas não avisa se, por
exemplo, a VM inteira cair, ficar sem rede, ou o processo ficar "preso" sem crashar. Um dead man's
switch externo (Healthchecks.io, grátis) cobre esse caso: o bot manda um ping HTTP a cada ciclo
bem-sucedido; se os pings pararem de chegar por tempo demais, o Healthchecks.io avisa — mesmo que
o bot/VM tenha sumido por completo e não consiga avisar ele mesmo.

### Criar o check grátis

1. Crie uma conta grátis em <https://healthchecks.io> (o plano grátis cobre esse uso tranquilo).
2. "Add Check" → dê um nome (ex. "signals-mvp POS-RUNNER") → período esperado (ex. "a cada 5
   minutos", de acordo com `ciclo.intervalo_s` do `config.yaml`) e um "Grace Time" generoso (ex.
   10-15 min, para não disparar falso-alarme num ciclo lento).
3. Copie a "Ping URL" que ele mostra (algo como `https://hc-ping.com/<uuid>`).

### Ligar no bot

```bash
echo "HEALTHCHECKS_URL=https://hc-ping.com/<uuid-que-voce-copiou>" >> signals_mvp/.env
sudo systemctl restart signals-mvp   # (ou reinicie o tmux, se nao estiver usando systemd)
```

Sem essa linha no `.env`, o bot não manda nenhum ping (comportamento padrão, zero chamada extra).
A URL **nunca aparece em log** (mesma trava do `TELEGRAM_BOT_TOKEN`) — mesmo assim, trate-a como
segredo: quem a tiver pode mandar pings falsos e mascarar uma queda real.

O bot manda:
- um ping "start" assim que liga;
- um ping normal ("ok") depois de cada ciclo que terminar sem erro;
- um ping "fail" se o loop principal cair num erro grave (o processo continua tentando se
  recuperar — o ping "fail" é só o aviso).

### Ligar o aviso no Telegram (ou e-mail)

No painel do check, em "Integrations", o Healthchecks.io já tem uma integração nativa de
**Telegram** (não precisa escrever nada): conecte sua conta/bot do Telegram pela integração deles
e escolha o chat que deve receber o aviso — pode ser o MESMO bot/chat que já recebe os alertas do
`signals_mvp`, ou outro separado, à sua escolha. A partir daí, qualquer atraso além do "Grace
Time" manda uma mensagem automática, sem precisar manter nenhum servidor de webhook seu.

### Alertas operacionais internos (PEDIDO ADICIONAL FASE 6, item 2)

Além do dead man's switch (bot inteiro sumiu), o POS-RUNNER-V1 já manda, sozinho, 1 aviso por
Telegram por **ocorrência** (nunca spam — só repete depois de normalizar e piorar de novo) quando:

- a taxa de **HTTP 429** do GeckoTerminal fica acima de um teto (padrão 30%) numa janela de tempo
  (padrão 2h) — sinal de que o IP está sendo limitado além do normal;
- a **fila de atualização** dos candles de 1h ainda não esvaziou **30 minutos** depois do
  fechamento da hora (padrão) — sinal de atraso real no acompanhamento, não só uma demora pontual.

Ambos têm padrão seguro e são ajustáveis por `.env` (`POS_RUNNER_429_TETO_PCT`,
`POS_RUNNER_429_JANELA_H`, `POS_RUNNER_FILA_ATRASO_MIN` — ver `signals_mvp/.env.example`); não
precisam de nenhum serviço externo.
