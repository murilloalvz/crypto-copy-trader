"""Telegram: cliente da Bot API, poller de botoes/comandos e registro das acoes do operador.

Seguranca:
  * so atende o TELEGRAM_CHAT_ID configurado (qualquer outro chat e ignorado);
  * o token nunca aparece em log/erro (excecoes do `requests` carregam a URL com o token —
    por isso so repassamos o NOME do tipo da excecao).
"""

from __future__ import annotations

import html
import io
import json
import logging
import re
import sqlite3
import threading
import zipfile
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
    def send_message(self, text: str, reply_markup: dict | None = None, parse_mode: str | None = "HTML",
                     reply_to: int | None = None) -> int:
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text[:4000],
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to:
            payload["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
        result = self.call("sendMessage", payload)
        return int(result["message_id"])

    def notify(self, text: str) -> None:
        """Aviso simples (texto puro escapado)."""
        self.send_message(html.escape(text, quote=False))

    def send_photo(self, png: bytes, caption: str, reply_markup: dict | None = None, parse_mode: str | None = "HTML",
                   reply_to: int | None = None) -> int:
        """Foto (mini-grafico) com legenda (ate 1024 caracteres). Quem chama cai para `send_message` se isto falhar."""
        url = f"{self._base}/bot{self._token}/sendPhoto"
        data: dict[str, Any] = {"chat_id": self.chat_id, "caption": caption[:1024]}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        if reply_to:
            data["reply_parameters"] = json.dumps({"message_id": int(reply_to), "allow_sending_without_reply": True})
        try:
            response = self.session.post(url, data=data, files={"photo": ("grafico.png", png, "image/png")},
                                         timeout=(5.0, self.timeout_s))
        except requests.RequestException as exc:
            raise TelegramError(f"rede: {type(exc).__name__}") from None  # nunca repassa a mensagem (tem a URL/token)
        try:
            body = response.json()
        except ValueError:
            raise TelegramError(f"resposta invalida (HTTP {response.status_code})", status=response.status_code) from None
        if not isinstance(body, dict) or not body.get("ok"):
            raise TelegramError(str((body or {}).get("description", "erro desconhecido"))[:200], status=response.status_code)
        return int(body["result"]["message_id"])

    def send_document(self, data: bytes, filename: str, caption: str = "") -> int:
        """Arquivo generico (PEDIDO ADICIONAL FASE 5, /exportar): mesmo padrao do `send_photo`, so
        que generico (zip/csv) e so para o chat ja autorizado (quem chama decide isso antes)."""
        url = f"{self._base}/bot{self._token}/sendDocument"
        data_payload: dict[str, Any] = {"chat_id": self.chat_id, "caption": caption[:1024]}
        try:
            response = self.session.post(
                url, data=data_payload, files={"document": (filename, data, "application/octet-stream")},
                timeout=(5.0, self.timeout_s),
            )
        except requests.RequestException as exc:
            raise TelegramError(f"rede: {type(exc).__name__}") from None  # nunca repassa a mensagem (tem a URL/token)
        try:
            body = response.json()
        except ValueError:
            raise TelegramError(f"resposta invalida (HTTP {response.status_code})", status=response.status_code) from None
        if not isinstance(body, dict) or not body.get("ok"):
            raise TelegramError(str((body or {}).get("description", "erro desconhecido"))[:200], status=response.status_code)
        return int(body["result"]["message_id"])

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

# PEDIDO ADICIONAL FASE 5, item 4: limite de tamanho do /exportar -- abaixo do teto de 50 MB do
# sendDocument do Telegram, com margem (nunca manda um arquivo que o Telegram vai recusar).
EXPORTAR_LIMITE_BYTES = 45 * 1024 * 1024

HELP_TEXT = (
    "Comandos:\n"
    "/entrei <contrato> <valor> [chain]\n"
    "/sai <contrato> <valor> [chain]\n"
    "/passei <contrato> [chain]\n"
    "/status - estado do bot\n"
    "/resumo - resumo de hoje\n"
    "Os botoes ✅ entrei / ⏭ passei do alerta registram a posicao padrao.\n"
    "Valores em USD (aceita 100 ou 100,5). [chain] so e preciso se o contrato nao for de um sinal "
    "recente e a chain for ambigua (ex.: 0x... em bsc ou robinhood).\n"
    "\n"
    "POS-RUNNER-V1 (feedback):\n"
    "/entrei <pool|ticker> [preco] - registra que entrou num sinal da V1 (preco real -> slippage vs o alerta)\n"
    "/sai <pool|ticker> [preco] - registra que saiu de um sinal da V1 (preco real -> slippage vs TP1/EXIT/stop)\n"
    "/nota <pool|ticker> <texto> - anota algo sobre o sinal\n"
    "/pulei <pool|ticker> <motivo> - registra que viu o sinal e NAO executou\n"
    "/scam <pool|ticker> [motivo] - marca manual de scam (nao bloqueia nem remove o sinal)\n"
    "/relatorio [v1|v2] - bons vs ruins da ultima semana (padrao v1)\n"
    "/abertos - posicoes paper abertas (V1 e V2), com R nao realizado\n"
    "/fechados [n] - ultimos n trades fechados (padrao 10), com R realizado e motivo da saida\n"
    "/exportar - manda um .zip com sinais, trades, feedback e divergencias de candle (sem segredos)\n"
    "Os botoes 👍 Bom / 👎 Ruim / 📝 Nota do alerta da V1 registram o voto/nota; o 📝 pede a nota em resposta."
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
        relatorio_provider: Callable[[list[str]], str] = lambda args: "sem relatorio",
        abertos_provider: Callable[[], str] = lambda: "sem posicoes",
        fechados_provider: Callable[[int], str] = lambda n: "sem fechados",
    ):
        self.client = client
        self.storage = storage
        self.get_config = get_config
        self.clock = clock
        self.status_provider = status_provider
        self.summary_provider = summary_provider
        self.relatorio_provider = relatorio_provider
        self.abertos_provider = abertos_provider
        self.fechados_provider = fechados_provider
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
            reply_to = msg.get("reply_to_message")
            if reply_to is not None and text and self._maybe_handle_note_reply(reply_to, text):
                return
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
        if command == "/relatorio":
            # PEDIDO CONSOLIDADO FASE 2: "/relatorio" aceita "v1" ou "v2" (padrao v1, compatibilidade
            # com o comando que ja existia antes da V2) -- nunca mistura as estatisticas das 2 versoes.
            return self.relatorio_provider(args)
        if command == "/nota":
            return self._v1_nota_command(args)
        if command == "/pulei":
            return self._v1_pulei_command(args)
        if command == "/scam":
            return self._v1_scam_command(args)
        if command == "/abertos":
            # PEDIDO ADICIONAL FASE 5, item 1: por versao (V1/V2), ultimo preco ja buscado (zero chamada nova).
            return self.abertos_provider()
        if command == "/fechados":
            # PEDIDO ADICIONAL FASE 5, item 2: "/fechados [n]" (padrao 10).
            n = 10
            if args:
                try:
                    n = max(1, int(args[0]))
                except ValueError:
                    return "Use: /fechados [n]"
            return self.fechados_provider(n)
        if command == "/exportar":
            return self._exportar_command()
        if command in ("/entrei", "/sai"):
            # FASE 3 da V1 (feedback no Telegram): MESMA grafia de comando do V0, formato diferente
            # (<pool|ticker> [preco], nao <contrato> <valor> [chain]) -- tenta resolver contra um sinal da
            # V1 primeiro; so cai pro comando classico do V0 se nao achar nada (nunca confunde os dois:
            # ticker nunca passa no formato de contrato que o V0 exige, e pool != endereco de token/mint).
            v1_reply = self._v1_trade_command(command[1:], args)
            if v1_reply is not None:
                return v1_reply
        if command in ("/entrei", "/sai", "/passei"):
            return self._trade_command(command[1:], args)
        return "Comando desconhecido. Use /ajuda."

    # -- FASE 3 da V1 (feedback no Telegram) -------------------------------------------------
    def _v1_resolve_signal_token(self, token: str) -> Optional[sqlite3.Row]:
        """`<pool|ticker>`: pool (endereco, chave exata em `pr1_signals`) OU ticker (simbolo, case-
        insensitive) -- o sinal mais recente que combina. `None` = nao e um sinal da V1 (quem chama decide
        o que fazer, nunca inventa um "nao encontrado" quando na verdade e o comando do V0)."""
        token = (token or "").strip()
        if not token:
            return None
        rows = self.storage.pr1_signals(pool=token)
        if not rows:
            rows = [r for r in self.storage.pr1_signals() if (r["symbol"] or "").lower() == token.lower()]
        return rows[-1] if rows else None

    @staticmethod
    def _v1_slippage_pct(preco_real: float, referencia: Optional[float]) -> Optional[float]:
        if not referencia:
            return None
        return 100.0 * (preco_real - referencia) / referencia

    @staticmethod
    def _v1_referencia_saida(signal: sqlite3.Row) -> Optional[float]:
        """Ultima referencia de preco que a V1 alcancou nesse sinal: EXIT FULL, senao TP1, senao o stop.
        None quando nenhuma existe ainda (nunca inventa referencia)."""
        for campo in ("exit_full_price", "tp1_price", "stop"):
            if signal[campo] is not None:
                return signal[campo]
        return None

    def _v1_trade_command(self, action: str, args: list[str]) -> Optional[str]:
        if not args:
            return None
        signal = self._v1_resolve_signal_token(args[0])
        if signal is None:
            return None   # nao achou sinal da V1: quem chama cai pro comando classico do V0
        preco: Optional[float] = None
        if len(args) > 1:
            preco = parse_amount(args[1])
            if preco is None:
                return "Preco invalido. Exemplo: 0.0021"
        assert self.client is not None
        slippage_entrada = slippage_saida = None
        if preco is not None:
            if action == "entrei":
                slippage_entrada = self._v1_slippage_pct(preco, signal["entry_price"])
            else:
                slippage_saida = self._v1_slippage_pct(preco, self._v1_referencia_saida(signal))
        self.storage.pr1_feedback_upsert(
            signal["id"], action, self.client.chat_id, self.clock(), valor=preco, preco_real=preco,
            slippage_entrada_pct=slippage_entrada, slippage_saida_pct=slippage_saida)
        self.storage.export_csvs()
        rotulo = "entrada" if action == "entrei" else "saida"
        preco_txt = f" @ {preco}" if preco is not None else ""
        slip = slippage_entrada if action == "entrei" else slippage_saida
        slip_txt = f" | slippage {slip:+.1f}%" if slip is not None else ""
        return f"✅ {rotulo} registrada (V1): ${clean_text(signal['symbol'] or '?', 20)}{preco_txt}{slip_txt}"

    def _v1_nota_command(self, args: list[str]) -> str:
        if len(args) < 2:
            return "Use: /nota <pool|ticker> <texto>"
        signal = self._v1_resolve_signal_token(args[0])
        if signal is None:
            return "Sinal da V1 nao encontrado para esse pool/ticker."
        texto = " ".join(args[1:]).strip()
        assert self.client is not None
        self.storage.pr1_feedback_upsert(signal["id"], "nota", self.client.chat_id, self.clock(), texto=texto)
        self.storage.export_csvs()
        return f"\U0001f4dd nota registrada (V1): ${clean_text(signal['symbol'] or '?', 20)}"

    def _v1_pulei_command(self, args: list[str]) -> str:
        """/pulei <pool|ticker> <motivo>: sinal da V1 que o operador VIU e decidiu NAO executar --
        registro separado de pr1_feedback (aqui nunca e um trade, so uma observacao)."""
        if len(args) < 2:
            return "Use: /pulei <pool|ticker> <motivo>"
        signal = self._v1_resolve_signal_token(args[0])
        motivo = " ".join(args[1:]).strip()
        assert self.client is not None
        chain = signal["chain"] if signal else None
        pool = signal["pool"] if signal else args[0]
        symbol = signal["symbol"] if signal else None
        versao = signal["versao_config_v1"] if signal else None
        self.storage.pr1_pulado_insert(self.clock(), chain, pool, symbol, motivo, self.client.chat_id, versao,
                                       signal["id"] if signal else None)
        self.storage.export_csvs()
        rotulo = clean_text(symbol or args[0], 20)
        return f"⏭ pulei registrado (V1): ${rotulo} ({clean_text(motivo, 60)})"

    def _v1_scam_command(self, args: list[str]) -> str:
        """/scam <pool|ticker> [motivo]: marca manual (PEDIDO ADICIONAL FASE 5, item 5) -- guardada em
        pr1_feedback (acao='scam', mesma tabela do voto/nota) junto do sinal. NUNCA bloqueia nem remove
        o sinal; so soma numa contagem informativa no /relatorio (`pr1_feedback_scam_count_since`)."""
        if not args:
            return "Use: /scam <pool|ticker> [motivo]"
        signal = self._v1_resolve_signal_token(args[0])
        if signal is None:
            return "Sinal da V1 nao encontrado para esse pool/ticker."
        motivo = " ".join(args[1:]).strip() or None
        assert self.client is not None
        self.storage.pr1_feedback_upsert(signal["id"], "scam", self.client.chat_id, self.clock(), texto=motivo)
        self.storage.export_csvs()
        rotulo = clean_text(signal["symbol"] or "?", 20)
        motivo_txt = f" ({clean_text(motivo, 60)})" if motivo else ""
        return f"🚩 marcado como scam (V1): ${rotulo}{motivo_txt}"

    def _exportar_command(self) -> str:
        """/exportar (PEDIDO ADICIONAL FASE 5, item 4): zip com sinais/trades/feedback/pulados/divergencias
        de candle (V1+V2), nunca o .env nem nenhum outro segredo -- so os CSVs ja estaveis do bot. Limite
        de tamanho (`EXPORTAR_LIMITE_BYTES`) e so manda pro chat ja autorizado (`process_update` ja filtrou)."""
        assert self.client is not None
        self.storage.export_csvs(force=True)
        paths = self.storage.paths
        arquivos = [
            paths.sinais_csv, paths.descartados_csv, paths.trades_csv,
            paths.pos_runner_v1_csv, paths.pos_runner_v1_filtrados_csv, paths.pos_runner_v1_banca_csv,
            paths.pos_runner_v1_feedback_csv, paths.pos_runner_v1_pulados_csv, paths.pos_runner_v1_dexpaprika_csv,
            paths.pos_runner_v2_csv, paths.pos_runner_v2_filtrados_csv, paths.pos_runner_v2_banca_csv,
        ]
        buf = io.BytesIO()
        incluidos = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in arquivos:
                if path.exists():
                    zf.write(path, arcname=path.name)
                    incluidos += 1
        if incluidos == 0:
            return "Nada para exportar ainda (nenhum CSV gerado)."
        data = buf.getvalue()
        if len(data) > EXPORTAR_LIMITE_BYTES:
            return (f"Exportação cancelada: {len(data) / 1_048_576:.1f} MB excede o limite de "
                     f"{EXPORTAR_LIMITE_BYTES / 1_048_576:.0f} MB (copie os CSVs direto da VM, ex. scp).")
        nome = f"signals_mvp_export_{int(self.clock())}.zip"
        try:
            self.client.send_document(
                data, nome, caption="Exportação: sinais, trades, feedback e divergências de candle (V1+V2, sem segredos)")
        except TelegramError as exc:
            return f"Falha ao enviar o arquivo: {exc}"
        return f"✅ exportado: {nome} ({len(data) / 1024:.0f} KB, {incluidos} arquivo(s))"

    def _maybe_handle_note_reply(self, reply_to_message: dict, text: str) -> bool:
        """O botao 📝 Nota manda um prompt com "(sinal #<id>)" embutido no proprio texto (sem estado novo no
        servidor -- ver `telegram_v1.note_prompt_text`/`NOTE_PROMPT_RE`); quando o operador RESPONDE a esse
        prompt, a resposta e a nota. `False` = a mensagem respondida nao era um prompt de nota (segue o
        roteamento normal, ex.: um comando)."""
        from .pos_runner.telegram_v1 import NOTE_PROMPT_RE

        match = NOTE_PROMPT_RE.search(reply_to_message.get("text") or "")
        if not match:
            return False
        signal_id = int(match.group(1))
        assert self.client is not None
        ok = self.storage.pr1_feedback_upsert(signal_id, "nota", self.client.chat_id, self.clock(), texto=text.strip())
        self.storage.export_csvs()
        self.client.send_message(f"\U0001f4dd nota registrada (sinal #{signal_id})." if ok else "Sinal nao encontrado.")
        return True

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
        trade_id = self.storage.add_operator_trade(self.clock(), chain, contract, action, value, signal["id"] if signal else None, "comando")
        pr_signal = None if signal else self.storage.pr_signal_for_contract(contract)
        if pr_signal is not None:
            self.storage.pr_link_trade(trade_id, pr_signal["id"])
        self.storage.export_csvs()
        if signal:
            related = f" | sinal: ${clean_text(signal['symbol'], 20)} ({signal['etiqueta']})"
        elif pr_signal is not None:
            related = f" | sinal POS-RUNNER: ${clean_text(pr_signal['symbol'], 20)} ({pr_signal['tf']})"
        else:
            related = " | sem sinal relacionado"
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
        if data.startswith("v1fb:"):
            self._handle_v1_feedback_callback(cb, data, cb_id)
            return
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

    # -- FASE 3 da V1: botoes de feedback (👍/👎/📝) -----------------------------------------
    def _handle_v1_feedback_callback(self, cb: dict, data: str, cb_id: str) -> None:
        assert self.client is not None
        parts = data.split(":")
        if len(parts) != 3:
            self.client.answer_callback(cb_id, "botao invalido")
            return
        _, action, raw_id = parts
        try:
            signal_id = int(raw_id)
        except ValueError:
            self.client.answer_callback(cb_id, "botao invalido")
            return
        signal = self.storage.pr1_signal(signal_id)
        if signal is None:
            self.client.answer_callback(cb_id, "sinal nao encontrado")
            return
        chat_id = str((((cb.get("message") or {}).get("chat")) or {}).get("id", ""))
        now = self.clock()
        if action == "up":
            self.storage.pr1_feedback_upsert(signal_id, "voto", chat_id, now, voto="bom")
            self.storage.export_csvs()
            self.client.answer_callback(cb_id, "👍 registrado")
        elif action == "down":
            self.storage.pr1_feedback_upsert(signal_id, "voto", chat_id, now, voto="ruim")
            self.storage.export_csvs()
            self.client.answer_callback(cb_id, "👎 registrado")
        elif action == "note":
            # idempotente so pra voto (UNIQUE(pr1_signal_id,acao) ja garante isto); o prompt da nota
            # (texto com "(sinal #<id>)" embutido, sem estado novo no servidor) e so mandado agora.
            self.client.answer_callback(cb_id, "responda esta mensagem com a nota")
            from .pos_runner import telegram_v1

            message = cb.get("message") or {}
            try:
                self.client.send_message(
                    telegram_v1.note_prompt_text(signal["symbol"] or "?", signal_id),
                    reply_markup={"force_reply": True, "input_field_placeholder": "Nota..."},
                    reply_to=message.get("message_id"),
                )
            except TelegramError as exc:
                log.debug("nao consegui mandar o prompt de nota: %s", exc)
        else:
            self.client.answer_callback(cb_id, "botao invalido")


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
                if exc.status == 409:
                    # Conflito: o Telegram so deixa UMA sessao de getUpdates por token (item 3 do
                    # deploy Linux) -- quase sempre significa duas instancias do bot rodando com o
                    # MESMO token (ex.: supervisor local + systemd na VM ao mesmo tempo).
                    self.last_error = "conflito 409: outra instancia deste bot (mesmo TELEGRAM_BOT_TOKEN) ja esta rodando getUpdates -- pare uma das duas"
                    log.error(self.last_error)
                else:
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
