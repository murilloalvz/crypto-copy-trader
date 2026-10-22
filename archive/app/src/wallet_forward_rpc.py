from urllib.error import URLError

from src.solana import SolanaClient


VALID_WALLET_FORWARD_COMMITMENTS = {"confirmed", "finalized"}


class WalletForwardSolanaClient(SolanaClient):
    """Solana RPC client with an explicit commitment for forward wallet research.

    The generic project client historically relied on the RPC default commitment. Forward
    latency experiments cannot leave that implicit because Solana defaults to ``finalized``
    when commitment is omitted. This client keeps the chosen commitment explicit in every
    signatures/transaction request so runs can be interpreted against the runtime label.

    Forward runs are long-lived collectors, so abrupt TCP disconnects must be normalized into
    the same transport-error path already handled by ``SolanaClient.call``. In particular,
    ``http.client.RemoteDisconnected`` inherits from ``ConnectionError`` but is not wrapped by
    urllib as ``URLError`` in every failure path. Converting it here preserves the existing
    retry/fallback policy without catching arbitrary programming errors.
    """

    def __init__(
        self,
        *,
        commitment: str,
        rpc_url: str | None = None,
        timeout: int = 30,
        fallback_urls: tuple[str, ...] | list[str] | None = None,
    ):
        normalized = commitment.strip().lower()
        if normalized not in VALID_WALLET_FORWARD_COMMITMENTS:
            raise ValueError("wallet forward commitment must be confirmed or finalized")
        super().__init__(rpc_url=rpc_url, timeout=timeout, fallback_urls=fallback_urls)
        self.commitment = normalized

    def _read_payload(self, request, context=None) -> dict:
        try:
            return super()._read_payload(request, context)
        except ConnectionError as exc:
            raise URLError(exc) from exc

    def signatures(self, address: str, limit: int, before: str | None = None) -> list[dict]:
        options: dict[str, object] = {
            "limit": limit,
            "commitment": self.commitment,
        }
        if before:
            options["before"] = before
        return self.call("getSignaturesForAddress", [address, options]) or []

    def transaction(self, signature: str) -> dict | None:
        return self.call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": self.commitment,
                },
            ],
        )

    def signature_statuses(self, signatures: list[str] | tuple[str, ...]) -> list[dict | None]:
        values = [str(item).strip() for item in signatures if str(item).strip()]
        if not values:
            return []
        if len(values) > 256:
            raise ValueError("getSignatureStatuses accepts at most 256 signatures per request")
        result = self.call(
            "getSignatureStatuses",
            [values, {"searchTransactionHistory": True}],
        ) or {}
        statuses = result.get("value") or []
        if len(statuses) != len(values):
            raise RuntimeError("Solana RPC returned an unexpected signature status count")
        return list(statuses)
