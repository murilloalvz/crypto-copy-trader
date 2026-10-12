"""Addendum DRAFT 2026-10-12 (decisao do operador): corrige a definicao de
"atividade" usada pelo gate de cobertura -- a causa real do criterio de
buckets do grupo baseline (94,37%, rodada anterior) nao era decoder nem
agregador via CPI (hipotese investigada e descartada pela evidencia real:
ver "Addendum -- correcao de implementacao do gate de cobertura" no DRAFT).
Era contar qualquer transacao bem-sucedida que REFERENCIA o pool como se
fosse atividade de preco, mesmo quando o PumpSwap nunca executa nele (ex.:
um agregador lendo o estado do pool pra decidir rota, sem trocar nada ali).

**Trade** = transacao bem-sucedida em que o PumpSwap EXECUTA um swap NESTE
pool (muda o estado das reservas). Testado comparando
preTokenBalances/postTokenBalances (e preBalances/postBalances em lamports,
para o caso defensivo da conta-cofre de quote ser SOL nativo em vez de WSOL
embrulhado) das duas contas-cofre do pool -- nunca assumido pelo program_id
de nivel superior nem pela mera presenca na lista de assinaturas.

Classificacao por transacao (addendum (b)):
- saldo nao mudou -> "not_trade" (fora do denominador, fora de qualquer
  contagem);
- saldo mudou SEM o PumpSwap aparecer como invoke/success nos logs ->
  "missing_genuine" (dentro do denominador, nao resolvido -- caso
  defensivo, esperado raro ou inexistente);
- saldo mudou COM execucao do PumpSwap -> "trade" (dentro do denominador,
  resolvido ou nao exatamente como ja era).

Um bucket de 5s so sai do denominador (fica "carregado") se TODAS as suas
transacoes bem-sucedidas forem not_trade (addendum (c)).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Literal

VERSION = "h2_trade_verification_v0"

TradeClassification = Literal["trade", "not_trade", "missing_genuine"]


def _account_keys(message: dict[str, Any]) -> list[str]:
    return [(k["pubkey"] if isinstance(k, dict) else k) for k in message.get("accountKeys", [])]


def find_vault_pubkeys(reference_tx: dict[str, Any], *, pool_address: str) -> tuple[str, str] | None:
    """A partir de UMA transacao ja decodificada (resolvida) deste pool,
    identifica as duas contas-cofre: as contas cujo `owner` nos saldos de
    token da transacao e o endereco do pool. None se nao achar exatamente
    2 (defensivo -- nunca adivinha um cofre)."""
    meta = reference_tx.get("meta") or {}
    message = reference_tx["transaction"]["message"]
    account_keys = _account_keys(message)
    balances = (meta.get("preTokenBalances") or []) + (meta.get("postTokenBalances") or [])
    indices = {b["accountIndex"] for b in balances if b.get("owner") == pool_address}
    if len(indices) != 2:
        return None
    pubkeys = tuple(sorted(account_keys[i] for i in indices))
    return pubkeys  # type: ignore[return-value]


def _pumpswap_invoked(logs: list[Any], *, pumpswap_program_id: str) -> bool:
    return any(pumpswap_program_id in str(line) for line in logs)


def _vault_balance_changed(tx: dict[str, Any], *, vault_pubkeys: tuple[str, str]) -> bool:
    message = tx["transaction"]["message"]
    account_keys = _account_keys(message)
    vault_indices = {i for i, key in enumerate(account_keys) if key in vault_pubkeys}
    if not vault_indices:
        return False  # cofres nem referenciados nesta tx -- nao pode ter mudado

    meta = tx.get("meta") or {}
    pre_tb = {b["accountIndex"]: b["uiTokenAmount"]["amount"] for b in (meta.get("preTokenBalances") or [])}
    post_tb = {b["accountIndex"]: b["uiTokenAmount"]["amount"] for b in (meta.get("postTokenBalances") or [])}
    pre_lamports = meta.get("preBalances") or []
    post_lamports = meta.get("postBalances") or []

    for idx in vault_indices:
        if pre_tb.get(idx) != post_tb.get(idx):
            return True
        # Addendum (b): checagem defensiva em lamports, para o caso da
        # conta-cofre de quote ser representada em SOL nativo em vez de
        # WSOL embrulhado (nao esperado para PumpSwap, mas verificado).
        if idx < len(pre_lamports) and idx < len(post_lamports) and pre_lamports[idx] != post_lamports[idx]:
            return True
    return False


def classify_transaction(
    tx: dict[str, Any], *, vault_pubkeys: tuple[str, str], pumpswap_program_id: str
) -> TradeClassification:
    """Addendum 2026-10-12 (a)/(b): classifica UMA transacao bem-sucedida
    que referencia o pool (ja filtrada por err=None antes de chegar aqui)."""
    if not _vault_balance_changed(tx, vault_pubkeys=vault_pubkeys):
        return "not_trade"
    logs = (tx.get("meta") or {}).get("logMessages") or []
    if _pumpswap_invoked(logs, pumpswap_program_id=pumpswap_program_id):
        return "trade"
    return "missing_genuine"


@dataclass(frozen=True)
class BucketTradeClassification:
    has_trade: bool
    has_missing_genuine: bool
    all_not_trade: bool


def classify_bucket(classifications: list[TradeClassification]) -> BucketTradeClassification:
    """Addendum 2026-10-12 (c): um bucket so sai do denominador (vira
    "carregado") se TODAS as transacoes bem-sucedidas forem not_trade.
    Lista vazia (bucket sem nenhuma transacao) conta como all_not_trade,
    mesmo tratamento de bucket vazio de sempre."""
    if not classifications:
        return BucketTradeClassification(has_trade=False, has_missing_genuine=False, all_not_trade=True)
    return BucketTradeClassification(
        has_trade="trade" in classifications,
        has_missing_genuine="missing_genuine" in classifications,
        all_not_trade=all(c == "not_trade" for c in classifications),
    )


# ------------------------------ self-check (sintetico, sem rede) -----------


PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
POOL_ADDRESS = "PoolAddr11111111111111111111111111111111111"
VAULT_BASE = "VaultBase111111111111111111111111111111111"
VAULT_QUOTE = "VaultQuote11111111111111111111111111111111"
OTHER_ACCOUNT = "SomeOtherAccount1111111111111111111111111111"


def _fake_tx(
    *,
    account_keys: list[str],
    pre_token_balances: list[dict[str, Any]],
    post_token_balances: list[dict[str, Any]],
    pre_balances: list[int] | None = None,
    post_balances: list[int] | None = None,
    logs: list[str] | None = None,
) -> dict[str, Any]:
    n = len(account_keys)
    return {
        "transaction": {"message": {"accountKeys": account_keys}},
        "meta": {
            "preTokenBalances": pre_token_balances,
            "postTokenBalances": post_token_balances,
            "preBalances": pre_balances or [0] * n,
            "postBalances": post_balances or [0] * n,
            "logMessages": logs or [],
        },
    }


def _self_check_find_vault_pubkeys() -> None:
    reference_tx = _fake_tx(
        account_keys=[POOL_ADDRESS, VAULT_BASE, VAULT_QUOTE, OTHER_ACCOUNT],
        pre_token_balances=[
            {"accountIndex": 1, "owner": POOL_ADDRESS, "uiTokenAmount": {"amount": "1000"}},
            {"accountIndex": 2, "owner": POOL_ADDRESS, "uiTokenAmount": {"amount": "2000"}},
            {"accountIndex": 3, "owner": "SomeoneElse", "uiTokenAmount": {"amount": "5"}},
        ],
        post_token_balances=[
            {"accountIndex": 1, "owner": POOL_ADDRESS, "uiTokenAmount": {"amount": "900"}},
            {"accountIndex": 2, "owner": POOL_ADDRESS, "uiTokenAmount": {"amount": "2200"}},
            {"accountIndex": 3, "owner": "SomeoneElse", "uiTokenAmount": {"amount": "5"}},
        ],
    )
    vaults = find_vault_pubkeys(reference_tx, pool_address=POOL_ADDRESS)
    assert vaults == tuple(sorted((VAULT_BASE, VAULT_QUOTE))), vaults

    # so 1 conta com esse owner -- nao acha exatamente 2, devolve None (nunca adivinha).
    one_owner_tx = _fake_tx(
        account_keys=[POOL_ADDRESS, VAULT_BASE],
        pre_token_balances=[{"accountIndex": 1, "owner": POOL_ADDRESS, "uiTokenAmount": {"amount": "1"}}],
        post_token_balances=[{"accountIndex": 1, "owner": POOL_ADDRESS, "uiTokenAmount": {"amount": "1"}}],
    )
    assert find_vault_pubkeys(one_owner_tx, pool_address=POOL_ADDRESS) is None


def _self_check_classify_transaction() -> None:
    vault_pubkeys = tuple(sorted((VAULT_BASE, VAULT_QUOTE)))
    account_keys = [POOL_ADDRESS, VAULT_BASE, VAULT_QUOTE, OTHER_ACCOUNT]

    # (a) referencia sem execucao: cofres presentes mas saldo IDENTICO, sem
    # invoke do PumpSwap nos logs -- not_trade (o caso real investigado:
    # agregador le o pool, nao executa swap nele).
    unchanged = _fake_tx(
        account_keys=account_keys,
        pre_token_balances=[
            {"accountIndex": 1, "uiTokenAmount": {"amount": "1000"}},
            {"accountIndex": 2, "uiTokenAmount": {"amount": "2000"}},
        ],
        post_token_balances=[
            {"accountIndex": 1, "uiTokenAmount": {"amount": "1000"}},
            {"accountIndex": 2, "uiTokenAmount": {"amount": "2000"}},
        ],
        logs=["Program ComputeBudget111111111111111111111111111111 invoke [1]"],
    )
    assert (
        classify_transaction(unchanged, vault_pubkeys=vault_pubkeys, pumpswap_program_id=PUMPSWAP_PROGRAM_ID)
        == "not_trade"
    )

    # cofres nem referenciados na tx -- trivialmente not_trade.
    not_referenced = _fake_tx(
        account_keys=[OTHER_ACCOUNT],
        pre_token_balances=[],
        post_token_balances=[],
    )
    assert (
        classify_transaction(not_referenced, vault_pubkeys=vault_pubkeys, pumpswap_program_id=PUMPSWAP_PROGRAM_ID)
        == "not_trade"
    )

    # (b) saldo mudou + PumpSwap executou -- trade normal (swap direto).
    direct_swap = _fake_tx(
        account_keys=account_keys,
        pre_token_balances=[
            {"accountIndex": 1, "uiTokenAmount": {"amount": "1000"}},
            {"accountIndex": 2, "uiTokenAmount": {"amount": "2000"}},
        ],
        post_token_balances=[
            {"accountIndex": 1, "uiTokenAmount": {"amount": "900"}},
            {"accountIndex": 2, "uiTokenAmount": {"amount": "2200"}},
        ],
        logs=[
            f"Program {PUMPSWAP_PROGRAM_ID} invoke [1]",
            "Program data: AAAA",
            f"Program {PUMPSWAP_PROGRAM_ID} success",
        ],
    )
    assert (
        classify_transaction(direct_swap, vault_pubkeys=vault_pubkeys, pumpswap_program_id=PUMPSWAP_PROGRAM_ID)
        == "trade"
    )

    # saldo mudou via lamports (quote nativo), token balances identicos,
    # com execucao -- ainda trade (checagem defensiva de lamports).
    lamports_change = _fake_tx(
        account_keys=account_keys,
        pre_token_balances=[{"accountIndex": 1, "uiTokenAmount": {"amount": "1000"}}],
        post_token_balances=[{"accountIndex": 1, "uiTokenAmount": {"amount": "1000"}}],
        pre_balances=[0, 0, 5_000_000_000, 0],
        post_balances=[0, 0, 4_900_000_000, 0],
        logs=[f"Program {PUMPSWAP_PROGRAM_ID} invoke [1]", f"Program {PUMPSWAP_PROGRAM_ID} success"],
    )
    assert (
        classify_transaction(lamports_change, vault_pubkeys=vault_pubkeys, pumpswap_program_id=PUMPSWAP_PROGRAM_ID)
        == "trade"
    )

    # (b) saldo mudou SEM o PumpSwap aparecer invocado -- missing genuino
    # (caso defensivo, nao esperado acontecer de verdade).
    changed_without_invoke = _fake_tx(
        account_keys=account_keys,
        pre_token_balances=[{"accountIndex": 1, "uiTokenAmount": {"amount": "1000"}}],
        post_token_balances=[{"accountIndex": 1, "uiTokenAmount": {"amount": "900"}}],
        logs=["Program ComputeBudget111111111111111111111111111111 invoke [1]"],
    )
    assert (
        classify_transaction(
            changed_without_invoke, vault_pubkeys=vault_pubkeys, pumpswap_program_id=PUMPSWAP_PROGRAM_ID
        )
        == "missing_genuine"
    )


def _self_check_classify_bucket() -> None:
    # bucket vazio (sem nenhuma transacao) -- all_not_trade, mesmo
    # tratamento de bucket vazio de sempre.
    empty = classify_bucket([])
    assert empty.all_not_trade is True and empty.has_trade is False

    # todas as transacoes do bucket sao not_trade -- sai do denominador.
    all_not_trade = classify_bucket(["not_trade", "not_trade"])
    assert all_not_trade.all_not_trade is True and all_not_trade.has_trade is False

    # 1 trade entre varias not_trade -- basta 1 para o bucket continuar no
    # denominador (addendum (c)).
    mixed = classify_bucket(["not_trade", "trade", "not_trade"])
    assert mixed.all_not_trade is False and mixed.has_trade is True

    # so missing_genuine (sem nenhum trade) -- continua no denominador,
    # nao resolvido, nunca "carregado".
    only_missing = classify_bucket(["missing_genuine"])
    assert only_missing.all_not_trade is False
    assert only_missing.has_trade is False
    assert only_missing.has_missing_genuine is True


def _self_check() -> None:
    _self_check_find_vault_pubkeys()
    _self_check_classify_transaction()
    _self_check_classify_bucket()
    print(
        "self-check OK: identificacao de cofres (owner==pool, nunca adivinha) + "
        "classificacao de transacao (referencia sem execucao -> not_trade; swap direto -> "
        "trade; mudanca via lamports -> trade; mudanca sem invoke -> missing_genuine) + "
        "classificacao de bucket (1 trade basta pra ficar no denominador; so not_trade "
        "sai; so missing_genuine fica sem resolver)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return 0
    print("Modulo de classificacao -- sem entrypoint de producao proprio (chamado pela recomputacao real).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
