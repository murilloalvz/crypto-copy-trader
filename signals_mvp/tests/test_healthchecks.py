"""PEDIDO CONSOLIDADO FASE 3: dead man's switch via Healthchecks.io -- sem rede (monkeypatch de
`requests.get`). Sem `HEALTHCHECKS_URL`, nada chama a rede; com ela, "ok"/"start"/"fail" mandam GET na
URL certa; falha de rede nunca levanta nem loga a URL."""

from __future__ import annotations

import logging
import unittest
from unittest import mock

from .. import healthchecks


class PingTests(unittest.TestCase):
    def test_no_url_never_calls_requests(self) -> None:
        with mock.patch("signals_mvp.healthchecks.requests.get") as get:
            healthchecks.ping(None, "ok")
            healthchecks.ping("", "start")
        get.assert_not_called()

    def test_ok_pings_the_base_url_with_no_suffix(self) -> None:
        with mock.patch("signals_mvp.healthchecks.requests.get") as get:
            healthchecks.ping("https://hc-ping.com/abc-123", "ok")
        get.assert_called_once_with("https://hc-ping.com/abc-123", timeout=healthchecks.TIMEOUT_S)

    def test_start_and_fail_append_the_suffix(self) -> None:
        with mock.patch("signals_mvp.healthchecks.requests.get") as get:
            healthchecks.ping("https://hc-ping.com/abc-123", "start")
        get.assert_called_once_with("https://hc-ping.com/abc-123/start", timeout=healthchecks.TIMEOUT_S)
        with mock.patch("signals_mvp.healthchecks.requests.get") as get:
            healthchecks.ping("https://hc-ping.com/abc-123/", "fail")   # barra no fim: nunca dobra
        get.assert_called_once_with("https://hc-ping.com/abc-123/fail", timeout=healthchecks.TIMEOUT_S)

    def test_network_failure_never_raises_and_never_logs_the_url(self) -> None:
        import requests

        with mock.patch("signals_mvp.healthchecks.requests.get", side_effect=requests.ConnectionError("boom")):
            with self.assertLogs("signals_mvp.healthchecks", level="WARNING") as captured:
                healthchecks.ping("https://hc-ping.com/segredo-nunca-aparece", "ok")
        full_log = "\n".join(captured.output)
        self.assertNotIn("segredo-nunca-aparece", full_log)
        self.assertNotIn("hc-ping.com", full_log)


if __name__ == "__main__":
    unittest.main()
