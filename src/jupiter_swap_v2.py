import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.causal_quotes import CausalQuoteObservation


JUPITER_SWAP_V2_BASE_URL = "https://api.jup.ag/swap/v2"


class JupiterOrderError(RuntimeError):
    pass


@dataclass(frozen=True)
class JupiterOrder:
    input_mint: str
    output_mint: str
    in_amount_raw: str
    out_amount_raw: str
    in_usd_value: float | None
    out_usd_value: float | None
    swap_usd_value: float | None
    slippage_bps: int | None
    price_impact_pct_points: float | None
    router: str | None
    mode: str | None
    request_id: str | None
    quote_id: str | None
    transaction: str | None
    last_valid_block_height: str | None
    expire_at: str | None
    error_code: int | None
    error_message: str | None
    observed_at: int

    @property
    def has_assembled_transaction(self) -> bool:
        return bool(self.transaction)


class JupiterSwapV2Client:
    """Read-only client for Jupiter Meta-Aggregator ``GET /order``.

    This class deliberately does not implement signing or ``POST /execute``. Supplying a
    taker public key can make Jupiter assemble a transaction, but this client never signs or
    submits it.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout: int = 15,
        base_url: str = JUPITER_SWAP_V2_BASE_URL,
    ):
        if not api_key.strip():
            raise ValueError("JUPITER_API_KEY is required")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def order(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_raw: int | str,
        taker: str | None = None,
        slippage_bps: int | None = None,
    ) -> JupiterOrder:
        if not input_mint.strip() or not output_mint.strip():
            raise ValueError("input_mint and output_mint are required")
        if input_mint == output_mint:
            raise ValueError("input_mint and output_mint must differ")
        try:
            amount = int(amount_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("amount_raw must be an integer") from exc
        if amount <= 0:
            raise ValueError("amount_raw must be positive")
        if slippage_bps is not None and not 0 <= slippage_bps <= 10_000:
            raise ValueError("slippage_bps must be between 0 and 10000")

        query: dict[str, str] = {
            "inputMint": input_mint.strip(),
            "outputMint": output_mint.strip(),
            "amount": str(amount),
        }
        if taker is not None:
            if not taker.strip():
                raise ValueError("taker cannot be empty")
            query["taker"] = taker.strip()
        if slippage_bps is not None:
            query["slippageBps"] = str(slippage_bps)

        request = Request(
            f"{self.base_url}/order?{urlencode(query)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "crypto-copy-trader/0.3",
                "x-api-key": self.api_key,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(exc)
            raise JupiterOrderError(
                f"Jupiter /order HTTP {exc.code}: {detail[:300]}"
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise JupiterOrderError(f"Jupiter /order unavailable: {exc}") from exc

        observed_at = int(time.time())
        if not isinstance(payload, dict):
            raise JupiterOrderError("Jupiter /order returned a non-object payload")
        if payload.get("error") and not payload.get("inAmount"):
            raise JupiterOrderError(str(payload.get("error")))
        return parse_jupiter_order(payload, observed_at=observed_at)


def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def parse_jupiter_order(payload: dict, *, observed_at: int) -> JupiterOrder:
    if observed_at < 0:
        raise ValueError("observed_at must be non-negative")
    required = ("inputMint", "outputMint", "inAmount", "outAmount")
    missing = [key for key in required if payload.get(key) in {None, ""}]
    if missing:
        raise JupiterOrderError("Jupiter order missing fields: " + ", ".join(missing))

    try:
        in_amount = int(payload["inAmount"])
        out_amount = int(payload["outAmount"])
    except (TypeError, ValueError) as exc:
        raise JupiterOrderError("Jupiter order amounts are invalid") from exc
    if in_amount <= 0 or out_amount <= 0:
        raise JupiterOrderError("Jupiter order amounts must be positive")

    transaction_value = payload.get("transaction")
    transaction = None if transaction_value is None else str(transaction_value)
    return JupiterOrder(
        input_mint=str(payload["inputMint"]),
        output_mint=str(payload["outputMint"]),
        in_amount_raw=str(in_amount),
        out_amount_raw=str(out_amount),
        in_usd_value=_optional_float(payload.get("inUsdValue")),
        out_usd_value=_optional_float(payload.get("outUsdValue")),
        swap_usd_value=_optional_float(payload.get("swapUsdValue")),
        slippage_bps=_optional_int(payload.get("slippageBps")),
        price_impact_pct_points=_optional_float(payload.get("priceImpact")),
        router=(str(payload["router"]) if payload.get("router") else None),
        mode=(str(payload["mode"]) if payload.get("mode") else None),
        request_id=(str(payload["requestId"]) if payload.get("requestId") else None),
        quote_id=(str(payload["quoteId"]) if payload.get("quoteId") else None),
        transaction=transaction,
        last_valid_block_height=(
            str(payload["lastValidBlockHeight"])
            if payload.get("lastValidBlockHeight") is not None
            else None
        ),
        expire_at=(str(payload["expireAt"]) if payload.get("expireAt") else None),
        error_code=_optional_int(payload.get("errorCode")),
        error_message=(
            str(payload["errorMessage"]) if payload.get("errorMessage") else None
        ),
        observed_at=observed_at,
    )


def jupiter_order_to_causal_quote(
    order: JupiterOrder,
    *,
    token_mint: str,
    side: str,
    token_decimals: int,
) -> CausalQuoteObservation:
    """Normalize one Jupiter order into a side-aware causal route quote.

    Jupiter does not expose a separate market timestamp for the quote, so ``market_time`` is
    conservatively set to the local receive time. A response is marked executable only when
    Jupiter actually returned an assembled transaction. This is still a *candidate route*,
    not proof that a future signed submission would land.
    """

    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if token_decimals < 0 or token_decimals > 18:
        raise ValueError("token_decimals must be between 0 and 18")
    token_mint = token_mint.strip()
    if not token_mint:
        raise ValueError("token_mint cannot be empty")

    scale = 10**token_decimals
    if side == "buy":
        if order.output_mint != token_mint:
            raise ValueError("buy order must output token_mint")
        token_quantity = int(order.out_amount_raw) / scale
        usd_value = order.in_usd_value
    else:
        if order.input_mint != token_mint:
            raise ValueError("sell order must input token_mint")
        token_quantity = int(order.in_amount_raw) / scale
        usd_value = order.out_usd_value

    if token_quantity <= 0:
        raise ValueError("normalized token quantity must be positive")
    if usd_value is None or usd_value <= 0:
        raise JupiterOrderError(
            "Jupiter order lacks the USD value required for normalized token price"
        )

    price_usd = usd_value / token_quantity
    router = order.router or "unknown"
    route_id = order.quote_id or order.request_id
    return CausalQuoteObservation(
        token_mint=token_mint,
        side=side,
        market_time=order.observed_at,
        observed_at=order.observed_at,
        price_usd=price_usd,
        source=f"jupiter_swap_v2_order:{router}",
        executable=order.has_assembled_transaction,
        resolution_seconds=1,
        liquidity_usd=None,
        input_mint=order.input_mint,
        output_mint=order.output_mint,
        input_amount_raw=order.in_amount_raw,
        output_amount_raw=order.out_amount_raw,
        route_id=route_id,
    )
