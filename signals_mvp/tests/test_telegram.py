"""Telegram: cliente real contra um servidor local que imita a Bot API; handler de comandos; poller."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Optional

from ..telegram import OperatorHandler, TelegramClient, TelegramError, TelegramPoller, detect_platform, parse_amount
from .fakes import EVM_TOKEN, SOL_TOKEN, FakeClock, FakeTelegram
from .helpers import Env, read_csv

TOKEN = "123456789:AAH-fake_token_for_unit_tests_0123"


class MockBotApi:
    """Servidor HTTP local: POST /bot<token>/<metodo> com JSON. Registra tudo e responde conforme configurado."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.answers: dict[str, list[tuple[int, dict]]] = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silencia
                pass

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                prefix = f"/bot{TOKEN}/"
                if not self.path.startswith(prefix):
                    self._send(404, {"ok": False, "description": "Not Found"})
                    return
                method = self.path[len(prefix):]
                outer.requests.append((method, payload))
                queue = outer.answers.get(method)
                if queue:
                    status, body = queue.pop(0)
                elif method == "sendMessage":
                    status, body = 200, {"ok": True, "result": {"message_id": 500 + len(outer.requests)}}
                elif method == "getUpdates":
                    status, body = 200, {"ok": True, "result": []}
                else:
                    status, body = 200, {"ok": True, "result": True}
                self._send(status, body)

            def _send(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class TelegramClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.api = MockBotApi()
        self.client = TelegramClient(TOKEN, "42", base_url=self.api.url, timeout_s=5)

    def tearDown(self) -> None:
        self.api.stop()

    def test_send_message_payload(self) -> None:
        markup = {"inline_keyboard": [[{"text": "x", "url": "https://a"}]]}
        message_id = self.client.send_message("<b>oi</b>", markup)
        method, payload = self.api.requests[0]
        self.assertEqual(method, "sendMessage")
        self.assertEqual(payload["chat_id"], "42")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertTrue(payload["disable_web_page_preview"])
        self.assertEqual(payload["reply_markup"], markup)
        self.assertGreater(message_id, 500)

    def test_plain_text_mode_omits_parse_mode(self) -> None:
        self.client.send_message("texto <puro>", parse_mode=None)
        self.assertNotIn("parse_mode", self.api.requests[0][1])

    def test_notify_escapes_html(self) -> None:
        self.client.notify("a <b> & c")
        self.assertEqual(self.api.requests[0][1]["text"], "a &lt;b&gt; &amp; c")

    def test_api_error_carries_retry_after(self) -> None:
        self.api.answers["sendMessage"] = [(429, {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 7}})]
        with self.assertRaises(TelegramError) as ctx:
            self.client.send_message("x")
        self.assertEqual(ctx.exception.retry_after, 7.0)
        self.assertEqual(ctx.exception.status, 429)

    def test_network_error_never_leaks_the_token_or_url(self) -> None:
        dead = TelegramClient(TOKEN, "42", base_url="http://127.0.0.1:1", timeout_s=2)
        with self.assertRaises(TelegramError) as ctx:
            dead.send_message("x")
        text = str(ctx.exception) + repr(ctx.exception)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("AAH-fake", text)
        self.assertNotIn("127.0.0.1", text)

    def test_invalid_credentials_are_rejected_early(self) -> None:
        with self.assertRaises(TelegramError):
            TelegramClient("sem-dois-pontos", "42")
        with self.assertRaises(TelegramError):
            TelegramClient(TOKEN, " ")

    def test_get_updates(self) -> None:
        self.api.answers["getUpdates"] = [(200, {"ok": True, "result": [{"update_id": 9, "message": {"text": "/ajuda", "chat": {"id": 42}}}]})]
        updates = self.client.get_updates(5, timeout=1)
        self.assertEqual(updates[0]["update_id"], 9)
        payload = self.api.requests[0][1]
        self.assertEqual((payload["offset"], payload["timeout"]), (5, 1))
        self.assertEqual(payload["allowed_updates"], ["message", "callback_query"])

    def test_callback_and_keyboard_edit(self) -> None:
        self.client.answer_callback("cb1", "registrado")
        self.client.edit_reply_markup(77, {"inline_keyboard": []})
        self.assertEqual([m for m, _ in self.api.requests], ["answerCallbackQuery", "editMessageReplyMarkup"])


class HandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Env()
        self.env.cycle(0)
        self.tg = FakeTelegram()
        self.handler = OperatorHandler(
            self.tg, self.env.storage, lambda: self.env.engine.cfg, FakeClock(),
            status_provider=lambda: "STATUS", summary_provider=lambda: "RESUMO",
        )

    def tearDown(self) -> None:
        self.env.close()

    def trades(self) -> list[dict]:
        return read_csv(self.env.paths.trades_csv)

    def test_parsing_helpers(self) -> None:
        self.assertEqual(parse_amount("100"), 100.0)
        self.assertEqual(parse_amount("100,5"), 100.5)
        self.assertEqual(parse_amount("$1.234,50"), 1234.5)
        self.assertEqual(parse_amount("1,234.50"), 1234.5)
        for bad in ("abc", "-5", "0", ""):
            self.assertIsNone(parse_amount(bad))
        self.assertEqual(detect_platform(EVM_TOKEN), "evm")
        self.assertEqual(detect_platform(SOL_TOKEN), "solana")
        self.assertIsNone(detect_platform("0x123"))
        self.assertIsNone(detect_platform("OlaMundo"))

    def test_entrei_for_solana_without_a_signal(self) -> None:
        reply = self.handler.handle_command(f"/entrei {SOL_TOKEN} 100")
        self.assertIn("entrei registrado", reply)
        self.assertIn("sem sinal relacionado", reply)
        row = self.trades()[0]
        self.assertEqual((row["chain"], row["contrato"], row["acao"], row["valor"], row["sinal_relacionado"]), ("solana", SOL_TOKEN, "entrei", "100.0", ""))

    def test_bot_suffix_and_case_insensitive_command(self) -> None:
        self.assertIn("registrado", self.handler.handle_command(f"/ENTREI@MeuBot {SOL_TOKEN} 50"))

    def test_usage_and_validation_errors_do_not_write(self) -> None:
        for text in ("/entrei", f"/entrei {SOL_TOKEN}", "/entrei lixo 100", f"/entrei {SOL_TOKEN} abc", f"/entrei {SOL_TOKEN} -3", "/sai", "/passei"):
            with self.subTest(text):
                reply = self.handler.handle_command(text)
                self.assertNotIn("registrado", reply)
        self.assertFalse(self.env.paths.trades_csv.exists() and self.trades())

    def test_evm_contract_needs_chain_when_ambiguous_then_accepts_it(self) -> None:
        reply = self.handler.handle_command(f"/entrei {EVM_TOKEN} 10")
        self.assertIn("Informe a chain", reply)
        self.assertIn("registrado", self.handler.handle_command(f"/entrei {EVM_TOKEN} 10 robinhood"))
        self.assertEqual(self.trades()[0]["chain"], "robinhood")
        self.assertIn("Chain desconhecida", self.handler.handle_command(f"/entrei {EVM_TOKEN} 10 ethereum"))
        self.assertIn("nao tem formato", self.handler.handle_command(f"/entrei {SOL_TOKEN} 10 bsc"))

    def test_chain_is_inferred_from_a_previous_signal(self) -> None:
        self.env.storage.insert_signal(dict(chain="robinhood", pool="0xp", token=EVM_TOKEN, symbol="RH", etiqueta="novo", decision_ts=1.0))
        reply = self.handler.handle_command(f"/sai {EVM_TOKEN.upper().replace('0X', '0x')} 75")
        self.assertIn("ROBINHOOD", reply)
        self.assertIn("$RH (novo)", reply)
        self.assertEqual(self.trades()[0]["sinal_relacionado"], "1970-01-01T00:00:01Z|novo")

    def test_passei_has_no_value(self) -> None:
        self.handler.handle_command(f"/passei {SOL_TOKEN}")
        self.assertEqual(self.trades()[0]["valor"], "")

    def test_info_commands(self) -> None:
        self.assertEqual(self.handler.handle_command("/status"), "STATUS")
        self.assertEqual(self.handler.handle_command("/resumo"), "RESUMO")
        self.assertIn("/entrei", self.handler.handle_command("/start"))
        self.assertIn("desconhecido", self.handler.handle_command("/xyz"))

    def test_unauthorized_chat_is_ignored(self) -> None:
        stranger = {"message": {"text": f"/entrei {SOL_TOKEN} 100", "chat": {"id": 999}}}
        self.handler.process_update(stranger)
        self.assertEqual(self.tg.sent, [])
        self.assertFalse(self.env.paths.trades_csv.exists() and self.trades())
        stranger_cb = {"callback_query": {"id": "x", "data": "e|1", "message": {"message_id": 1, "chat": {"id": 999}}}}
        self.handler.process_update(stranger_cb)
        self.assertEqual(self.tg.answers, [])

    def test_callback_for_unknown_signal(self) -> None:
        self.handler.process_update({"callback_query": {"id": "c", "data": "e|999", "message": {"message_id": 1, "chat": {"id": 42}}}})
        self.assertEqual(self.tg.answers[-1], ("c", "sinal nao encontrado"))
        self.handler.process_update({"callback_query": {"id": "c2", "data": "noop", "message": {"message_id": 1, "chat": {"id": 42}}}})
        self.assertEqual(self.tg.answers[-1], ("c2", ""))


class PollerTest(unittest.TestCase):
    def test_poller_processes_allowed_updates_and_persists_offset(self) -> None:
        api = MockBotApi()
        env = Env()
        try:
            client = TelegramClient(TOKEN, "42", base_url=api.url, timeout_s=5)
            api.answers["getUpdates"] = [(200, {"ok": True, "result": [
                {"update_id": 10, "message": {"text": f"/entrei {SOL_TOKEN} 20", "chat": {"id": 42}}},
                {"update_id": 11, "message": {"text": f"/entrei {SOL_TOKEN} 30", "chat": {"id": 7}}},   # estranho
                {"update_id": 12, "message": {"text": "bom dia", "chat": {"id": 42}}},                  # nao e comando
            ]})]
            handler = OperatorHandler(client, env.storage, lambda: env.engine.cfg, FakeClock())
            stop = threading.Event()
            poller = TelegramPoller(client, handler, env.storage, stop, poll_timeout=1)
            poller.start()
            for _ in range(100):
                if env.storage.get_meta("tg_offset") == "13":
                    break
                stop.wait(0.05)
            stop.set()
            poller.join(timeout=5)
            self.assertEqual(env.storage.get_meta("tg_offset"), "13")
            rows = read_csv(env.paths.trades_csv)
            self.assertEqual([(r["acao"], r["valor"]) for r in rows], [("entrei", "20.0")])
            replies = [p["text"] for m, p in api.requests if m == "sendMessage"]
            self.assertEqual(len(replies), 1)  # so o comando do chat autorizado foi respondido
            self.assertFalse(poller.is_alive())
        finally:
            env.close()
            api.stop()

    def test_poller_survives_api_errors(self) -> None:
        api = MockBotApi()
        env = Env()
        try:
            client = TelegramClient(TOKEN, "42", base_url=api.url, timeout_s=5)
            api.answers["getUpdates"] = [(500, {"ok": False, "description": "boom"}), (200, {"ok": True, "result": [{"update_id": 1, "message": {"text": "/status", "chat": {"id": 42}}}]})]
            handler = OperatorHandler(client, env.storage, lambda: env.engine.cfg, FakeClock(), status_provider=lambda: "vivo")
            stop = threading.Event()
            poller = TelegramPoller(client, handler, env.storage, stop, poll_timeout=1)
            poller.start()
            for _ in range(200):
                if any(m == "sendMessage" for m, _ in api.requests):
                    break
                stop.wait(0.05)
            stop.set()
            poller.join(timeout=8)
            self.assertTrue(any(p.get("text") == "vivo" for m, p in api.requests if m == "sendMessage"))
        finally:
            env.close()
            api.stop()


_ = (Callable, Optional)

if __name__ == "__main__":
    unittest.main()
