#!/usr/bin/env bash
# Liga o bot de sinais (PAPER / somente leitura) em Linux. Espelha signals_mvp/iniciar.bat.
#
# Uso manual (dentro de uma sessao tmux, por exemplo):
#   signals_mvp/scripts/linux/iniciar.sh
#
# Para rodar como servico de sistema (reinicia so, sobrevive a reboot), use o
# systemd unit em signals_mvp/scripts/linux/signals-mvp.service -- ver
# docs/DEPLOY_VPS_LINUX.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

export PYTHONIOENCODING=utf-8

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  PYTHON="python"
fi

echo "Bot de sinais de memecoins - PAPER / somente leitura. Nada aqui compra ou vende."
echo "Para parar: Ctrl+C (se estiver em foreground) ou rode parar.sh em outra sessao."
echo

exec "$PYTHON" -m signals_mvp iniciar "$@"
