"""PEDIDO CONSOLIDADO FASE 3: dead man's switch opcional via Healthchecks.io (ou qualquer servico
compativel com o mesmo protocolo de ping HTTP). So leitura/efeito colateral de rede nenhum sobre o
bot em si -- um GET de "estou vivo". SEM a env `HEALTHCHECKS_URL`, nada disto faz qualquer chamada.

A URL contem um UUID secreto (quem a tiver pode mandar pings falsos); por isso ela NUNCA aparece em
log, nem em texto de erro -- so a palavra "ok"/"start"/"fail" (o tipo do ping), nunca a URL."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("signals_mvp.healthchecks")

TIMEOUT_S = 10.0


def ping(base_url: str | None, kind: str = "ok") -> None:
    """`kind`: "ok" (ciclo bem sucedido, GET na URL base), "start" (inicio, GET .../start) ou "fail"
    (erro grave, GET .../fail). Convencao do Healthchecks.io: https://healthchecks.io/docs/http_api/
    Nunca levanta -- um dead man's switch que derruba o bot por falha de rede seria pior que nao ter."""
    if not base_url:
        return
    url = base_url.rstrip("/")
    if kind != "ok":
        url = f"{url}/{kind}"
    try:
        requests.get(url, timeout=TIMEOUT_S)
    except requests.RequestException:
        log.warning("healthchecks: ping (%s) falhou (sem rede ou URL invalida -- nunca logada)", kind)
