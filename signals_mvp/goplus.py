"""Cliente da GoPlus Security API (publica). Devolve registros crus; a decisao e do security.py.

Formato (capturado em 2026-10-13):
  EVM    GET /token_security/{chain_id}?contract_addresses=a,b   -> result{ "<endereco minusculo>": {...} }
  Solana GET /solana/token_security?contract_addresses=a,b       -> result{ "<mint>": {...} }
Token novo costuma NAO aparecer em `result` (ausente) ou vir como registro-casca; ambos = "sem dado".
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from .http import ApiError, HttpClient

log = logging.getLogger("signals_mvp.goplus")


def parse_security_response(data: Any, platform: str, requested: Sequence[str]) -> dict[str, Optional[dict]]:
    """token pedido -> registro cru (dict) ou None quando a GoPlus nao devolveu nada para ele."""
    if not isinstance(data, dict):
        raise ApiError("bad_json", "GoPlus: resposta nao e objeto")
    result = data.get("result")
    code = data.get("code")
    if not isinstance(result, dict):
        # code != 1 sem resultado = erro de verdade (ex.: endereco invalido, limite)
        raise ApiError("http", f"GoPlus: code={code!r} message={data.get('message')!r}", status=None)
    index = {str(k).lower(): v for k, v in result.items()} if platform == "evm" else result
    out: dict[str, Optional[dict]] = {}
    for token in requested:
        key = token.lower() if platform == "evm" else token
        record = index.get(key)
        out[token] = record if isinstance(record, dict) and record else None
    return out


class GoPlusClient:
    def __init__(self, http: HttpClient, batch_max: int = 20):
        self.http = http
        self.batch_max = max(1, batch_max)

    def security(
        self, platform: str, chain_id: str, tokens: Sequence[str]
    ) -> tuple[dict[str, Optional[dict]], Optional[ApiError]]:
        """Consulta em lotes. Devolve (resultados dos lotes que deram certo, primeiro erro ou None).

        Token ausente do dicionario = nao foi consultado (lote falhou); valor None = consultado e
        a GoPlus nao tem dado.
        """
        results: dict[str, Optional[dict]] = {}
        error: Optional[ApiError] = None
        unique = list(dict.fromkeys(tokens))
        for start in range(0, len(unique), self.batch_max):
            chunk = unique[start : start + self.batch_max]
            if platform == "solana":
                path = "solana/token_security"
            else:
                path = f"token_security/{chain_id}"
            try:
                data = self.http.get_json(path, {"contract_addresses": ",".join(chunk)})
                results.update(parse_security_response(data, platform, chunk))
            except ApiError as exc:
                log.warning("GoPlus %s falhou (%s)", chain_id, exc)
                error = error or exc
                if exc.kind == "rate_limited":
                    break
        return results, error
