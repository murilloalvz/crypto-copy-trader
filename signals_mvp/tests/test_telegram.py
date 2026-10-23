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


class V1FeedbackHandlerTest(unittest.TestCase):
    """FASE 3 (feedback no Telegram): botoes 👍/👎/📝 e comandos /entrei, /sai, /nota, /relatorio da V1."""

    def setUp(self) -> None:
        self.env = Env()
        self.env.cycle(0)
        self.tg = FakeTelegram()
        self.handler = OperatorHandler(
            self.tg, self.env.storage, lambda: self.env.engine.cfg, FakeClock(),
            status_provider=lambda: "STATUS", summary_provider=lambda: "RESUMO",
            relatorio_provider=lambda: "RELATORIO SEMANAL",
        )
        self.signal_id = self.env.storage.pr1_insert_signal({
            "chain": "solana", "pool": "poolA", "tf": "1h", "evento": "ENTRADA", "ts_fechamento": 1_000,
            "mint": "mintA", "symbol": "CAT", "launchpad": "pumpfun", "dex": "pumpswap",
            "versao_config_v1": "abc123", "gatilho": "[]", "tags": "[]", "janela_ouro": "janela_ouro",
            "hora_brt": "09:00", "origem": "trending", "event_json": "{}", "status": "aberto",
            "entry_price": 1.0, "stop": 0.9, "topo": 2.0, "s_suporte": 0.95, "r_resistencia": 1.5,
        })

    def tearDown(self) -> None:
        self.env.close()

    def _feedback_rows(self):
        return self.env.storage.pr1_feedback_for_signal(self.signal_id)

    def _cb(self, data: str, chat: int = 42, message_id: int = 1, cb_id: str = "c") -> dict:
        return {"callback_query": {"id": cb_id, "data": data, "message": {"message_id": message_id, "chat": {"id": chat}}}}

    def test_vote_up_then_down_is_idempotent_updates_not_duplicates(self) -> None:
        self.handler.process_update(self._cb(f"v1fb:up:{self.signal_id}"))
        self.assertEqual(self.tg.answers[-1], ("c", "👍 registrado"))
        rows = self._feedback_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["voto"], "bom")
        self.handler.process_update(self._cb(f"v1fb:down:{self.signal_id}", cb_id="c2"))
        self.assertEqual(self.tg.answers[-1], ("c2", "👎 registrado"))
        rows = self._feedback_rows()
        self.assertEqual(len(rows), 1, "clicar 2x tem que ATUALIZAR a mesma linha, nunca duplicar")
        self.assertEqual(rows[0]["voto"], "ruim")

    def test_invalid_callback_data_never_crashes(self) -> None:
        for bad in (f"v1fb:bogus:{self.signal_id}", "v1fb:up", "v1fb:up:abc", "v1fb:up:999999"):
            with self.subTest(bad):
                self.handler.process_update(self._cb(bad))
                self.assertIn(self.tg.answers[-1][1], ("botao invalido", "sinal nao encontrado"))
        self.assertEqual(len(self._feedback_rows()), 0)

    def test_unauthorized_chat_is_ignored_for_v1_feedback_too(self) -> None:
        self.handler.process_update(self._cb(f"v1fb:up:{self.signal_id}", chat=999))
        self.assertEqual(self.tg.answers, [])
        self.assertEqual(self._feedback_rows(), [])

    def test_note_button_prompts_in_reply_and_the_reply_is_recorded(self) -> None:
        self.handler.process_update(self._cb(f"v1fb:note:{self.signal_id}", message_id=7))
        self.assertEqual(self.tg.answers[-1], ("c", "responda esta mensagem com a nota"))
        prompt_text, markup = self.tg.sent[-1]
        self.assertIn(f"sinal #{self.signal_id}", prompt_text)
        self.assertTrue(markup.get("force_reply"))
        self.assertEqual(self.tg.replies[-1], 7)
        reply_update = {"message": {"text": "entrada excelente", "chat": {"id": 42},
                                    "reply_to_message": {"text": prompt_text}}}
        self.handler.process_update(reply_update)
        rows = self._feedback_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["acao"], "nota")
        self.assertEqual(rows[0]["texto"], "entrada excelente")

    def test_v1_entrei_sai_nota_commands_by_pool_and_ticker(self) -> None:
        reply = self.handler.handle_command(f"/entrei poolA 0.0021")
        self.assertIn("entrada registrada (V1)", reply)
        self.assertIn("CAT", reply)
        reply = self.handler.handle_command("/sai CAT 0.0030")
        self.assertIn("saida registrada (V1)", reply)
        rows = self._feedback_rows()
        self.assertEqual({r["acao"] for r in rows}, {"entrei", "sai"})
        reply = self.handler.handle_command("/nota CAT bom gatilho")
        self.assertIn("nota registrada (V1)", reply)
        self.assertEqual(self.handler.handle_command("/nota semprevaizero"), "Use: /nota <pool|ticker> <texto>")

    def test_v1_commands_never_shadow_the_classic_v0_entrei_for_a_real_contract(self) -> None:
        """Mesma grafia de comando (/entrei), formato diferente -- um contrato que nao e nem pool nem ticker
        de nenhum sinal da V1 tem que continuar caindo no comando classico do V0, sem regressao."""
        reply = self.handler.handle_command(f"/entrei {SOL_TOKEN} 100")
        self.assertIn("entrei registrado", reply)   # resposta do V0 (_trade_command), nao da V1

    def test_relatorio_command_calls_the_provider(self) -> None:
        self.assertEqual(self.handler.handle_command("/relatorio"), "RELATORIO SEMANAL")

    def test_help_mentions_the_new_v1_commands(self) -> None:
        help_text = self.handler.handle_command("/ajuda")
        for token in ("/nota", "/relatorio", "/pulei", "👍 Bom"):
            self.assertIn(token, help_text)

    def test_entrei_with_real_price_records_slippage_against_the_alert_entry(self) -> None:
        # entry_price=1.0 no fixture; preco real 1.1 -> 10% de slippage contra o preco do alerta.
        reply = self.handler.handle_command("/entrei poolA 1.1")
        self.assertIn("slippage +10.0%", reply)
        rows = self._feedback_rows()
        self.assertEqual(rows[0]["acao"], "entrei")
        self.assertAlmostEqual(rows[0]["preco_real"], 1.1)
        self.assertAlmostEqual(rows[0]["slippage_entrada_pct"], 10.0)
        self.assertIsNone(rows[0]["slippage_saida_pct"])

    def test_sai_with_real_price_falls_back_to_the_stop_when_no_tp1_or_exit_full_yet(self) -> None:
        # sem tp1_price/exit_full_price no fixture: a referencia de saida cai pro stop (0.9).
        reply = self.handler.handle_command("/sai poolA 0.85")
        self.assertIn("slippage -5.6%", reply)
        rows = self._feedback_rows()
        self.assertEqual(rows[0]["acao"], "sai")
        self.assertAlmostEqual(rows[0]["preco_real"], 0.85)
        self.assertAlmostEqual(rows[0]["slippage_saida_pct"], -5.555555555555556)
        self.assertIsNone(rows[0]["slippage_entrada_pct"])

    def test_entrei_sem_preco_nao_calcula_slippage(self) -> None:
        reply = self.handler.handle_command("/entrei poolA")
        self.assertNotIn("slippage", reply)
        rows = self._feedback_rows()
        self.assertIsNone(rows[0]["preco_real"])
        self.assertIsNone(rows[0]["slippage_entrada_pct"])

    def test_pulei_records_a_separate_row_never_in_pr1_feedback(self) -> None:
        reply = self.handler.handle_command("/pulei poolA liquidez baixa")
        self.assertIn("pulei registrado (V1)", reply)
        self.assertIn("CAT", reply)
        self.assertIn("liquidez baixa", reply)
        self.assertEqual(self._feedback_rows(), [], "/pulei nunca pode criar linha em pr1_feedback")
        rows = self.env.storage.pr1_pulados()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pool"], "poolA")
        self.assertEqual(rows[0]["motivo"], "liquidez baixa")
        self.assertEqual(rows[0]["pr1_signal_id"], self.signal_id)

    def test_pulei_without_a_known_signal_still_records_best_effort(self) -> None:
        reply = self.handler.handle_command("/pulei TICKERDESCONHECIDO nao gostei")
        self.assertIn("pulei registrado (V1)", reply)
        rows = self.env.storage.pr1_pulados()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["pr1_signal_id"])
        self.assertEqual(rows[0]["pool"], "TICKERDESCONHECIDO")

    def test_pulei_usage_error(self) -> None:
        self.assertEqual(self.handler.handle_command("/pulei poolA"), "Use: /pulei <pool|ticker> <motivo>")


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

    def test_409_conflict_gets_a_clear_distinct_message(self) -> None:
        """FASE 1 do deploy Linux (item 3): duas instancias com o MESMO token fazendo getUpdates ->
        o Telegram devolve 409. O poller nunca pode confundir isso com um erro generico."""
        api = MockBotApi()
        env = Env()
        try:
            client = TelegramClient(TOKEN, "42", base_url=api.url, timeout_s=5)
            api.answers["getUpdates"] = [
                (409, {"ok": False, "description": "Conflict: terminated by other getUpdates request"}),
                (200, {"ok": True, "result": []}),
            ]
            handler = OperatorHandler(client, env.storage, lambda: env.engine.cfg, FakeClock())
            stop = threading.Event()
            poller = TelegramPoller(client, handler, env.storage, stop, poll_timeout=1)
            poller.start()
            for _ in range(200):
                if poller.last_error is not None:
                    break
                stop.wait(0.02)
            stop.set()
            poller.join(timeout=8)
            self.assertIsNotNone(poller.last_error)
            self.assertIn("409", poller.last_error)
            self.assertIn("outra instancia", poller.last_error)
        finally:
            env.close()
            api.stop()


_ = (Callable, Optional)

if __name__ == "__main__":
    unittest.main()
