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
