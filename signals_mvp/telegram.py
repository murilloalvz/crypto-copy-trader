"""Telegram: cliente da Bot API, poller de botoes/comandos e registro das acoes do operador.

Seguranca:
  * so atende o TELEGRAM_CHAT_ID configurado (qualquer outro chat e ignorado);
  * o token nunca aparece em log/erro (excecoes do `requests` carregam a URL com o token —
    por isso so repassamos o NOME do tipo da excecao).
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
from typing import Any, Callable, Optional

import requests

from .alerts import keyboard_after_choice
from .config import Config
from .storage import Storage
from .util import clean_text, fmt_money, fmt_usd, to_float

log = logging.getLogger("signals_mvp.telegram")


class TelegramError(Exception):
    def __init__(self, message: str, retry_after: float | None = None, status: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.status = status


class TelegramClient:
    def __init__(
        self,
        token: str,
        chat_id: str,
        base_url: str = "https://api.telegram.org",
        session: requests.Session | None = None,
        timeout_s: float = 20.0,
    ):
        if not token or ":" not in token:
            raise TelegramError("TELEGRAM_BOT_TOKEN ausente ou em formato invalido (esperado 123456:ABC...)")
        if not str(chat_id).strip():
            raise TelegramError("TELEGRAM_CHAT_ID ausente")
        self._token = token
        self.chat_id = str(chat_id).strip()
        self._base = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout_s = timeout_s

    @property
    def secrets(self) -> tuple[str, ...]:
        return (self._token,)

    def call(self, method: str, payload: dict | None = None, read_timeout: float | None = None) -> Any:
        url = f"{self._base}/bot{self._token}/{method}"
        try:
            response = self.session.post(url, json=payload or {}, timeout=(5.0, read_timeout or self.timeout_s))
        except requests.RequestException as exc:
            raise TelegramError(f"rede: {type(exc).__name__}") from None  # nunca repassa a mensagem (tem a URL/token)
        try:
            data = response.json()
        except ValueError:
            raise TelegramError(f"resposta invalida (HTTP {response.status_code})", status=response.status_code) from None
        if not isinstance(data, dict) or not data.get("ok"):
            params = (data or {}).get("parameters") or {}
            raise TelegramError(
                str((data or {}).get("description", "erro desconhecido"))[:200],
                retry_after=to_float(params.get("retry_after")),
                status=response.status_code,
            )
        return data.get("result")

    # -- envio -----------------------------------------------------------------------------
    def send_message(self, text: str, reply_markup: dict | None = None, parse_mode: str | None = "HTML") -> int:
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text[:4000],
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result = self.call("sendMessage", payload)
        return int(result["message_id"])

    def notify(self, text: str) -> None:
        """Aviso simples (texto puro escapado)."""
        self.send_message(html.escape(text, quote=False))

    def edit_reply_markup(self, message_id: int, reply_markup: dict) -> None:
        self.call("editMessageReplyMarkup", {"chat_id": self.chat_id, "message_id": message_id, "reply_markup": reply_markup})

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})

    def get_updates(self, offset: int, timeout: int = 25) -> list[dict]:
        payload = {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        result = self.call("getUpdates", payload, read_timeout=timeout + 10)
        return result if isinstance(result, list) else []

    def get_me(self) -> dict:
        return self.call("getMe")


# ---------------------------------------------------------------------------
# comandos do operador
# ---------------------------------------------------------------------------

_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

HELP_TEXT = (
    "Comandos:\n"
    "/entrei <contrato> <valor> [chain]\n"
    "/sai <contrato> <valor> [chain]\n"
    "/passei <contrato> [chain]\n"
    "/status - estado do bot\n"
    "/resumo - resumo de hoje\n"
    "Os botoes ✅ entrei / ⏭ passei do alerta registram a posicao padrao.\n"
    "Valores em USD (aceita 100 ou 100,5). [chain] so e preciso se o contrato nao for de um sinal "
    "recente e a chain for ambigua (ex.: 0x... em bsc ou robinhood)."
)


def detect_platform(contract: str) -> Optional[str]:
    if _EVM_RE.match(contract):
        return "evm"
    if _SOL_RE.match(contract):
        return "solana"
    return None


def parse_amount(text: str) -> Optional[float]:
    """'100', '100,5', '$1.234,50' e '1,234.50' => numero. Com os dois separadores, o ULTIMO e o decimal;
    com um so (ponto ou virgula) ele e decimal — para milhar, escreva sem separador."""
    cleaned = text.strip().replace("US$", "").lstrip("$").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        decimal, thousands = ("," , ".") if cleaned.rfind(",") > cleaned.rfind(".") else (".", ",")
        cleaned = cleaned.replace(thousands, "").replace(decimal, ".")
    else:
        cleaned = cleaned.replace(",", ".")
    value = to_float(cleaned)
    return value if value is not None and value > 0 else None


def short_contract(contract: str) -> str:
    return contract if len(contract) <= 14 else f"{contract[:6]}...{contract[-4:]}"


class OperatorHandler:
    """Processa updates do Telegram. `handle_command` e puro o bastante para testar sem rede."""

    def __init__(
        self,
        client: Optional[TelegramClient],
        storage: Storage,
        get_config: Callable[[], Config],
        clock: Callable[[], float],
        status_provider: Callable[[], str] = lambda: "sem status",
        summary_provider: Callable[[], str] = lambda: "sem resumo",
    ):
        self.client = client
        self.storage = storage
        self.get_config = get_config
        self.clock = clock
        self.status_provider = status_provider
        self.summary_provider = summary_provider
        self._warned_chats: set[str] = set()

    # -- roteamento ------------------------------------------------------------------------
    def process_update(self, update: dict) -> None:
        assert self.client is not None
        if "callback_query" in update:
            cb = update["callback_query"] or {}
            chat = str((((cb.get("message") or {}).get("chat")) or {}).get("id", ""))
            if not self._allowed(chat):
                return
            self._handle_callback(cb)
        elif "message" in update:
            msg = update["message"] or {}
            chat = str(((msg.get("chat")) or {}).get("id", ""))
            if not self._allowed(chat):
                return
            text = (msg.get("text") or "").strip()
            if text.startswith("/"):
                reply = self.handle_command(text)
                if reply:
                    self.client.send_message(html.escape(reply, quote=False))

    def _allowed(self, chat_id: str) -> bool:
        assert self.client is not None
        if chat_id == self.client.chat_id:
            return True
        if chat_id not in self._warned_chats:
            self._warned_chats.add(chat_id)
            log.warning("ignorando mensagem de chat nao autorizado (id %s)", chat_id)
        return False

    # -- comandos ---------------------------------------------------------------------------
    def handle_command(self, text: str) -> str:
        parts = text.split()
        command = parts[0].lower().split("@", 1)[0]
        args = parts[1:]
        if command in ("/start", "/ajuda", "/help"):
            return HELP_TEXT
        if command == "/status":
            return self.status_provider()
        if command == "/resumo":
            return self.summary_provider()
        if command in ("/entrei", "/sai", "/passei"):
            return self._trade_command(command[1:], args)
        return "Comando desconhecido. Use /ajuda."

    def _trade_command(self, action: str, args: list[str]) -> str:
        cfg = self.get_config()
        needs_value = action in ("entrei", "sai")
        usage = f"Use: /{action} <contrato>{' <valor>' if needs_value else ''} [chain]"
        if len(args) < (2 if needs_value else 1):
            return usage
        contract = args[0].strip()
        platform = detect_platform(contract)
        if platform is None:
            return "Contrato invalido (esperado 0x... com 40 hex, ou endereco Solana)."
        value: Optional[float] = None
        rest = args[1:]
        if needs_value:
            value = parse_amount(rest[0])
            if value is None:
                return "Valor invalido. Exemplo: 100 ou 100,5"
            rest = rest[1:]
        explicit = rest[0].lower() if rest else None
        contract = contract.lower() if platform == "evm" else contract
        chain, error = self._resolve_chain(contract, platform, explicit, cfg)
        if chain is None:
            return error or "Nao consegui descobrir a chain."
        signals = self.storage.signals_for_contract(contract, chain)
        signal = signals[0] if signals else None
        self.storage.add_operator_trade(self.clock(), chain, contract, action, value, signal["id"] if signal else None, "comando")
        self.storage.export_csvs()
        related = f" | sinal: ${clean_text(signal['symbol'], 20)} ({signal['etiqueta']})" if signal else " | sem sinal relacionado"
        amount = f" | US$ {fmt_money(value)}" if value is not None else ""
        return f"✅ {action} registrado: {cfg.chain(chain)['nome']} {short_contract(contract)}{amount}{related}"

    def _resolve_chain(self, contract: str, platform: str, explicit: Optional[str], cfg: Config) -> tuple[Optional[str], Optional[str]]:
        chains = cfg.raw["chains"]
        if explicit:
            if explicit not in chains:
                return None, f"Chain desconhecida: {explicit}. Opcoes: {', '.join(chains)}"
            if chains[explicit]["plataforma"] != platform:
                return None, f"O contrato nao tem formato de {explicit}."
            return explicit, None
        known = {row["chain"] for row in self.storage.signals_for_contract(contract)}
        if len(known) == 1:
            return next(iter(known)), None
        if len(known) > 1:
            return None, f"Contrato em mais de uma chain ({', '.join(sorted(known))}). Informe a chain no fim do comando."
        candidates = [name for name, c in cfg.enabled_chains().items() if c["plataforma"] == platform]
        if len(candidates) == 1:
            return candidates[0], None
        return None, f"Informe a chain no fim do comando ({', '.join(candidates) or 'nenhuma ligada'})."

    # -- botoes ------------------------------------------------------------------------------
    def _handle_callback(self, cb: dict) -> None:
        assert self.client is not None
        data = str(cb.get("data", ""))
        cb_id = str(cb.get("id", ""))
        if data == "noop" or "|" not in data:
            self.client.answer_callback(cb_id)
            return
        kind, _, raw_id = data.partition("|")
        try:
            signal_id = int(raw_id)
        except ValueError:
            self.client.answer_callback(cb_id, "botao invalido")
            return
        signal = self.storage.get_signal(signal_id)
        if signal is None or kind not in ("e", "p"):
            self.client.answer_callback(cb_id, "sinal nao encontrado")
            return
        action = "entrei" if kind == "e" else "passei"
        if self.storage.operator_action_for(signal_id) == action:
            self.client.answer_callback(cb_id, f"ja registrado: {action}")
            return
        try:
            plan = json.loads(signal["plano_json"] or "{}")
        except ValueError:
            plan = {}
        value = float(plan.get("posicao_usd", 0)) if action == "entrei" and plan.get("posicao_usd") else None
        self.storage.add_operator_trade(self.clock(), signal["chain"], signal["token"], action, value, signal_id, "botao")
        self.storage.export_csvs()
        label = "✅ entrei" if action == "entrei" else "⏭ passei"
        if value:
            label += f" (US$ {fmt_usd(value)})"
        self.client.answer_callback(cb_id, f"registrado: {action}")
        message = cb.get("message") or {}
        rows = ((message.get("reply_markup") or {}).get("inline_keyboard")) or []
        message_id = message.get("message_id")
        if message_id:
            try:
                self.client.edit_reply_markup(int(message_id), keyboard_after_choice(rows, label))
            except TelegramError as exc:
                log.debug("nao consegui atualizar o teclado: %s", exc)


class TelegramPoller(threading.Thread):
    """Long polling em thread propria: os botoes respondem mesmo com o ciclo principal ocupado."""

    def __init__(self, client: TelegramClient, handler: OperatorHandler, storage: Storage, stop: threading.Event, poll_timeout: int = 25):
        super().__init__(name="telegram-poller", daemon=True)
        self.client = client
        self.handler = handler
        self.storage = storage
        self.stop_event = stop
        self.poll_timeout = poll_timeout
        self.last_error: Optional[str] = None

    def run(self) -> None:
        try:
            self._loop()
        except Exception:  # noqa: BLE001 - no desligamento o banco pode ja ter fechado: sai quieto
            if not self.stop_event.is_set():
                log.exception("poller do Telegram caiu")

    def _loop(self) -> None:
        offset = int(self.storage.get_meta("tg_offset", "0") or 0)
        backoff = 2.0
        while not self.stop_event.is_set():
            try:
                updates = self.client.get_updates(offset, self.poll_timeout)
                backoff = 2.0
                self.last_error = None
            except TelegramError as exc:
                self.last_error = str(exc)
                log.warning("Telegram getUpdates falhou: %s", exc)
                self.stop_event.wait(max(backoff, exc.retry_after or 0))
                backoff = min(60.0, backoff * 2)
                continue
            for update in updates:
                if self.stop_event.is_set():
                    return  # nao processa nada novo durante o desligamento (o update fica para a proxima execucao)
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                try:
                    self.handler.process_update(update)
                except Exception:  # noqa: BLE001 - uma mensagem ruim nao pode derrubar o poller
                    log.exception("erro ao processar update do Telegram")
                self.storage.set_meta("tg_offset", str(offset))
            if not updates:
                self.stop_event.wait(0.2)
