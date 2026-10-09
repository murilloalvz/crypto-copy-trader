"""SIG-FAST H2 Fase 1 (mandato autonomo, 2026-10-09) -- enumeracao de
migracoes SEM depender de Helius.

Helius `getTransactionsForAddress` (filtro blockTime nativo) bateu 429
sustentado 4x nesta sessao, sempre na enumeracao -- bloqueador recorrente,
nao um evento isolado. Este modulo substitui esse metodo por um caminho que
usa SO RPC padrao (getSlot/getBlockTime/getBlock/getSignaturesForAddress/
getTransaction, disponiveis em QuickNode/publico, nao exclusivos da Helius):

1. busca binaria por um slot cujo blockTime >= window_end (nunca por baixo --
   undershoot perderia transacoes no limite da janela);
2. 1 assinatura desse bloco como ancora "antes";
3. `getSignaturesForAddress(MIGRATION_AUTHORITY, before=ancora)` paginando
   pra tras at'e passar de window_start;
4. mantem so `err is None`;
5. `getTransaction` confirma CreatePool (mesma logica de
   `_touches_pumpfun_programs`/`_extract_pool_mint` que o caminho Helius ja
   usa -- reaproveitada, nao reescrita);
6. dedup por pool_mint.

Retorna `list[MigrationCandidate]` -- mesmo tipo e mesma assinatura posicional
de `fetch_migrations_in_windows` (so troca `rpc_url: str` por
`rotator: EndpointRotator`), pra plugar sem mudanca em `seal_block`.

Validacao de paridade OBRIGATORIA (operador, mandato autonomo Fase 1) contra
a janela (1784814600, 1784815200) do piloto real (ja enumerada via Helius,
`artifacts/sig_fast_h2_pilot_v0/checkpoint.json`) -- ver
`PILOT_KNOWN_WINDOW`/`PILOT_KNOWN_POOL_MINTS` e `--validate-parity`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benchmarks.move_first_h_coverage_audit_v0.sample_migration_account import (
    MIGRATION_AUTHORITY,
    _extract_pool_mint,
    _touches_pumpfun_programs,
)
from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import EndpointRotator, MigrationCandidate

VERSION = "sig_fast_h2_enumeration_no_helius_v0"

# Alvo de tempo de slot da rede Solana -- so uma ESTIMATIVA inicial pra
# comecar a busca binaria perto do certo; nunca e o resultado final (a
# busca sempre confirma via blockTime real do slot resolvido).
AVG_SLOT_SECONDS = 0.4

# Quantos slots pular pra frente (NUNCA pra tras) procurando um bloco real
# quando o slot pedido foi pulado (sem bloco). Corridas de slots pulados no
# mainnet raramente passam de poucas unidades; isto e uma folga generosa.
MAX_SKIPPED_SLOT_NUDGE = 50

# Teto duro de iteracoes da busca binaria -- garante terminacao mesmo num
# trecho patologicamente cheio de lacunas (falha explicita, nunca um loop
# infinito nem uma resposta errada por baixo).
MAX_BRACKET_EXPANSIONS = 40
MAX_BINARY_SEARCH_ITERATIONS = 64

SIGNATURES_PAGE_SIZE = 1000


class SlotTimeUnresolvable(RuntimeError):
    """Nao foi possivel resolver um blockTime/assinatura real nem com o
    nudge-pra-frente esgotado -- falha explicita, nunca um valor por baixo
    (undershoot) nem uma resposta inventada."""


def _get_block_time(rotator: EndpointRotator, slot: int) -> int | None:
    """None = slot pulado (sem bloco) -- um FATO valido sobre o slot, nao um
    erro de transporte (getBlockTime de slot pulado volta como erro JSON-RPC
    de nivel de aplicacao, HTTP 200, nunca uma excecao). Qualquer falha de
    transporte real propaga e e tratada pelo rotator/rate-limiter, nao aqui."""
    result = rotator.call("getBlockTime", [slot])
    value = result.get("result")
    if value is None:
        return None
    return int(value)


def _resolve_forward(rotator: EndpointRotator, slot: int) -> tuple[int, int]:
    """(slot_real, blockTime) do primeiro slot >= `slot` com bloco --
    NUNCA um slot menor que o pedido (preserva a garantia de nunca
    undershoot). Levanta SlotTimeUnresolvable se o nudge esgotar."""
    probe = max(slot, 0)
    for _ in range(MAX_SKIPPED_SLOT_NUDGE + 1):
        block_time = _get_block_time(rotator, probe)
        if block_time is not None:
            return probe, block_time
        probe += 1
    raise SlotTimeUnresolvable(
        f"sem blockTime resolvivel a partir do slot {slot} (nudge de {MAX_SKIPPED_SLOT_NUDGE} esgotado)"
    )


def _estimate_slot_for_timestamp(rotator: EndpointRotator, target_time: int) -> int:
    current_slot = rotator.call("getSlot", [{"commitment": "confirmed"}])["result"]
    ref_slot, ref_time = _resolve_forward(rotator, max(current_slot - MAX_SKIPPED_SLOT_NUDGE, 0))
    estimated = ref_slot - int((ref_time - target_time) / AVG_SLOT_SECONDS)
    return max(estimated, 0)


def find_slot_at_or_after(
    rotator: EndpointRotator, target_time: int, *, slot_hint: int | None = None
) -> tuple[int, int]:
    """Menor slot RESOLVIVEL cujo blockTime >= target_time -- nunca por
    baixo (ver docstring do modulo). `slot_hint` existe so pra self-checks
    deterministicos (evita precisar simular getSlot/current_slot)."""
    estimate = slot_hint if slot_hint is not None else _estimate_slot_for_timestamp(rotator, target_time)

    lo_slot, lo_time = _resolve_forward(rotator, estimate)
    step = max(int(60 / AVG_SLOT_SECONDS), 1)

    if lo_time >= target_time:
        # Estimativa ja passou do alvo -- expande pra TRAS ate achar um
        # "lo" com blockTime < target_time (ou chegar ao slot 0).
        hi_slot, hi_time = lo_slot, lo_time
        for _ in range(MAX_BRACKET_EXPANSIONS):
            probe_slot = max(hi_slot - step, 0) if lo_slot == hi_slot else max(lo_slot - step, 0)
            lo_slot, lo_time = _resolve_forward(rotator, probe_slot)
            if lo_time < target_time or probe_slot == 0:
                break
            step *= 2
        else:
            raise SlotTimeUnresolvable(f"nao conseguiu delimitar por baixo perto de target_time={target_time}")
        if lo_time >= target_time:
            # target_time e <= o blockTime do slot 0 resolvivel -- o proprio
            # slot 0 (ou o mais proximo resolvivel dele) ja e a resposta.
            return lo_slot, lo_time
    else:
        hi_slot, hi_time = lo_slot, lo_time
        for _ in range(MAX_BRACKET_EXPANSIONS):
            if hi_time >= target_time:
                break
            hi_slot, hi_time = _resolve_forward(rotator, hi_slot + step)
            step *= 2
        else:
            raise SlotTimeUnresolvable(f"nao conseguiu delimitar por cima perto de target_time={target_time}")

    lo, hi = lo_slot, hi_slot
    for _ in range(MAX_BINARY_SEARCH_ITERATIONS):
        if hi - lo <= 1:
            break
        mid = (lo + hi) // 2
        mid_slot, mid_time = _resolve_forward(rotator, mid)
        if mid_time >= target_time:
            if mid_slot >= hi:
                # Nudge-pra-frente a partir de `mid` (que e > lo por
                # construcao) atravessou uma lacuna e caiu em `hi` ou
                # depois -- nao existe nada resolvivel estritamente entre
                # lo e hi: `hi` ja e a resposta mais justa, para aqui em
                # vez de girar sem nunca encolher o intervalo.
                break
            hi = mid_slot
        else:
            # mid_slot >= mid > lo sempre (nudge so vai pra frente) --
            # progresso de lo garantido por construcao, nunca estagna.
            lo = mid_slot
    else:
        raise SlotTimeUnresolvable(f"busca binaria nao convergiu pra target_time={target_time}")

    return _resolve_forward(rotator, hi)


def _resolve_anchor_signature(rotator: EndpointRotator, slot: int) -> str:
    """1a assinatura (qualquer transacao real, nao precisa tocar a conta de
    migracao) de um bloco >= `slot` -- serve de ancora `before` pra paginar
    getSignaturesForAddress da conta de migracao a partir deste ponto no
    tempo, sem ter que caminhar o historico inteiro dela."""
    probe = slot
    for _ in range(MAX_SKIPPED_SLOT_NUDGE + 1):
        result = rotator.call(
            "getBlock",
            [probe, {"transactionDetails": "signatures", "maxSupportedTransactionVersion": 1, "rewards": False}],
        )
        block = result.get("result")
        if block is not None:
            signatures = block.get("signatures") or []
            if signatures:
                return signatures[-1]
        probe += 1
    raise SlotTimeUnresolvable(f"nenhuma assinatura resolvivel a partir do slot {slot} (nudge esgotado)")


def _confirm_create_pool(rotator: EndpointRotator, signature: str) -> MigrationCandidate | None:
    """Mesma confirmacao que o caminho Helius ja usa (operador,
    fetch_migrations_in_windows): toca programa bonding-curve/PumpSwap, log
    "Instruction: CreatePool", meta.err is None, pool_mint extraivel --
    reaproveita `_touches_pumpfun_programs`/`_extract_pool_mint` em vez de
    reescrever a logica de confirmacao."""
    tx = rotator.call("getTransaction", [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
    tx_result = tx.get("result")
    if tx_result is None:
        return None
    message = tx_result["transaction"]["message"]
    if not _touches_pumpfun_programs(message):
        return None
    logs = (tx_result.get("meta") or {}).get("logMessages") or []
    if not any("Instruction: CreatePool" in line for line in logs):
        return None
    if (tx_result.get("meta") or {}).get("err") is not None:
        return None
    pool_mint = _extract_pool_mint(message)
    if not pool_mint:
        return None
    block_time = tx_result.get("blockTime")
    return MigrationCandidate(
        pool_mint=pool_mint,
        migration_signature=signature,
        migration_block_time=block_time if block_time is not None else 0,
    )


def fetch_migrations_in_window_no_helius(
    rotator: EndpointRotator, *, window_start: int, window_end: int
) -> list[MigrationCandidate]:
    """Fase 1: mesmo contrato de retorno de `fetch_migrations_in_windows`
    (lista de MigrationCandidate dedupada por pool_mint), mas via RPC
    padrao com rodizio (QuickNode/publico primeiro, Helius so como ultimo
    recurso dentro do proprio `rotator`) em vez de Helius exclusivo."""
    anchor_slot, _anchor_time = find_slot_at_or_after(rotator, window_end)
    anchor_signature = _resolve_anchor_signature(rotator, anchor_slot)

    seen_pools: set[str] = set()
    candidates: list[MigrationCandidate] = []
    before = anchor_signature
    while True:
        result = rotator.call(
            "getSignaturesForAddress", [MIGRATION_AUTHORITY, {"before": before, "limit": SIGNATURES_PAGE_SIZE}]
        )
        rows = result.get("result") or []
        if not rows:
            break
        reached_window_start = False
        for row in rows:
            block_time = row.get("blockTime")
            if block_time is None:
                continue
            if block_time < window_start:
                reached_window_start = True
                break
            if block_time >= window_end or row.get("err") is not None:
                continue
            candidate = _confirm_create_pool(rotator, row["signature"])
            if candidate is None or candidate.pool_mint in seen_pools:
                continue
            seen_pools.add(candidate.pool_mint)
            candidates.append(candidate)
        if reached_window_start or len(rows) < SIGNATURES_PAGE_SIZE:
            break
        before = rows[-1]["signature"]
    return candidates


# -- Validacao de paridade obrigatoria (operador, mandato autonomo Fase 1) ---
# Janela real ja enumerada via Helius no piloto (artifacts/sig_fast_h2_pilot_v0/
# checkpoint.json, recomputada deterministicamente via
# sample_calendar_windows(start_date="2026-07-21", end_date="2026-08-20",
# window_minutes=10, k=3, seed=20261008) -- a 1a das 3 janelas sorteadas).
PILOT_KNOWN_WINDOW: tuple[int, int] = (1784814600, 1784815200)
PILOT_KNOWN_POOL_MINTS: frozenset[str] = frozenset(
    {
        "9QRxnG9CkEE47ghdG8Jhbx9aoGCVw3woBM9Rdrv9pump",
        "2gD9aqqcqyLdvVGxN1MWdfsu43YFvGrc3CoDAnaNpump",
        "DZQehws9GcRPnCrUT5qBBV3WGno1YB9CBXwW51K6pump",
        "5haZLURnA964CpVYBUZv6qVrcD2gMDioPa3YUCoipump",
        "ATmBUD7mBW18n89QFsUiis1YeP9KW8xZTZawF6Dmpump",
        "AywxJj2BdixBePV82ZHwEadgWpcKxhMUFDXDhm2kpump",
        "2uiR1iRerF5bTuh2WvHcB4FftcZ6VDaFBReETtpypump",
    }
)


@dataclass(frozen=True)
class ParityValidationResult:
    window: tuple[int, int]
    expected_pool_mints: frozenset[str]
    found_pool_mints: frozenset[str]
    passed: bool
    missing: frozenset[str]
    unexpected: frozenset[str]


def validate_parity_against_pilot(rotator: EndpointRotator) -> ParityValidationResult:
    """Roda o metodo novo na MESMA janela que o piloto ja enumerou via
    Helius e compara pool_mint a pool_mint. NAO deve ser chamado dentro de
    --self-check (precisa de rede real) -- so por `--validate-parity`."""
    window_start, window_end = PILOT_KNOWN_WINDOW
    found = fetch_migrations_in_window_no_helius(rotator, window_start=window_start, window_end=window_end)
    found_mints = frozenset(c.pool_mint for c in found)
    return ParityValidationResult(
        window=PILOT_KNOWN_WINDOW,
        expected_pool_mints=PILOT_KNOWN_POOL_MINTS,
        found_pool_mints=found_mints,
        passed=found_mints == PILOT_KNOWN_POOL_MINTS,
        missing=PILOT_KNOWN_POOL_MINTS - found_mints,
        unexpected=found_mints - PILOT_KNOWN_POOL_MINTS,
    )


# ------------------------------ self-checks ---------------------------------


class _FakeChain:
    """Cadeia sintetica deterministica: slots -> blockTime, com lacunas
    (slots pulados) de proposito, e um conjunto de assinaturas por slot --
    prova a busca binaria e a paginacao sem precisar de rede real."""

    def __init__(self) -> None:
        # 1 slot a cada 2 (os impares sao "pulados" -- sem bloco), blockTime
        # = slot // 2 segundos a partir de epoch 0. current_slot = 2000.
        self.current_slot = 2000
        self.skipped = {s for s in range(0, 2001) if s % 2 == 1}
        self.signatures_by_slot: dict[int, list[str]] = {}
        # Transacoes da conta de migracao: um dict signature -> row (igual
        # ao formato getSignaturesForAddress), mais um dict signature -> tx
        # completa (getTransaction) pras confirmaveis.
        self.migration_signatures: list[dict[str, Any]] = []
        self.tx_by_signature: dict[str, dict[str, Any]] = {}
        # Registro GLOBAL de blockTime por assinatura (ancoras de bloco E
        # transacoes de migracao) -- `before` no RPC real posiciona pela
        # ordem cronologica da assinatura NA CADEIA TODA, nao exige que ela
        # pertenca a conta sendo consultada (a ancora normalmente NAO
        # pertence a MIGRATION_AUTHORITY). Modela isso por blockTime, nao
        # por lookup posicional dentro da lista de uma conta especifica.
        self.block_time_by_signature: dict[str, int] = {}

    def block_time(self, slot: int) -> int | None:
        if slot in self.skipped or slot < 0 or slot > self.current_slot:
            return None
        return slot // 2

    def add_block_signature(self, slot: int, signature: str) -> None:
        self.signatures_by_slot.setdefault(slot, []).append(signature)
        block_time = self.block_time(slot)
        if block_time is not None:
            self.block_time_by_signature[signature] = block_time

    def add_migration_tx(
        self, *, signature: str, block_time: int, pool_mint: str | None, err: Any = None, is_create_pool: bool = True
    ) -> None:
        self.migration_signatures.append({"signature": signature, "blockTime": block_time, "err": err})
        self.block_time_by_signature[signature] = block_time
        if not is_create_pool:
            logs = ["Program log: Instruction: SomethingElse"]
        else:
            logs = ["Program log: Instruction: CreatePool"]
        account_keys = [{"pubkey": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"}]
        if pool_mint:
            account_keys.append({"pubkey": pool_mint})
        self.tx_by_signature[signature] = {
            "slot": block_time * 2,
            "blockTime": block_time,
            "transaction": {"signatures": [signature], "message": {"accountKeys": account_keys}},
            "meta": {"logMessages": logs, "err": err},
        }

    def rpc(self, rpc_url: str, method: str, params: list, *, retries: int = 5) -> dict:
        if method == "getSlot":
            return {"result": self.current_slot}
        if method == "getBlockTime":
            slot = params[0]
            bt = self.block_time(slot)
            return {"result": bt} if bt is not None else {"error": {"message": "Block not available"}}
        if method == "getBlock":
            slot = params[0]
            bt = self.block_time(slot)
            if bt is None:
                return {"result": None}
            return {"result": {"signatures": self.signatures_by_slot.get(slot, [])}}
        if method == "getSignaturesForAddress":
            address, opts = params
            assert address == MIGRATION_AUTHORITY, address
            before = opts.get("before")
            ordered = sorted(self.migration_signatures, key=lambda r: r["blockTime"], reverse=True)
            if before is not None:
                # `before` posiciona pela ordem cronologica GLOBAL da
                # assinatura-ancora, nao por pertencer a esta conta (igual
                # ao RPC real) -- ver block_time_by_signature.
                before_time = self.block_time_by_signature[before]
                ordered = [r for r in ordered if r["blockTime"] < before_time]
            limit = opts.get("limit", 1000)
            return {"result": ordered[:limit]}
        if method == "getTransaction":
            signature = params[0]
            return {"result": self.tx_by_signature.get(signature)}
        raise AssertionError(f"unexpected RPC call in self-check: {method} {params}")


def _self_check_binary_search() -> None:
    from unittest.mock import patch

    chain = _FakeChain()
    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc", side_effect=chain.rpc
    ):
        rotator = EndpointRotator(["fake://rpc"])

        # target_time=500 -> blockTime = slot//2 -- queremos o MENOR slot
        # resolvivel com blockTime >= 500, ou seja slot 1000 (par, nao
        # pulado) com blockTime exatamente 500.
        slot, block_time = find_slot_at_or_after(rotator, 500)
        assert block_time >= 500, (slot, block_time)
        assert slot == 1000, (slot, block_time)

        # target_time num blockTime cujo slot exato seria IMPAR (pulado) --
        # tem que nudged pra FRENTE (nunca pra tras): blockTime=501 so
        # existiria no slot 1002 (par) pois slot 1001 (blockTime 500) e
        # impar/pulado -- a busca tem que achar slot>=1002 com tempo>=501,
        # nunca um slot<1002 (que seria < 501, undershoot proibido).
        slot2, block_time2 = find_slot_at_or_after(rotator, 501)
        assert block_time2 >= 501, (slot2, block_time2)
        assert slot2 % 2 == 0, (slot2, block_time2)  # nunca um slot pulado

        # target_time perto (mas nao sobre) a ponta da cadeia conhecida --
        # a estimativa linear inicial ainda tem que convergir pro valor
        # exato sem nunca passar por baixo do alvo.
        slot3, block_time3 = find_slot_at_or_after(rotator, 990)
        assert block_time3 >= 990, (slot3, block_time3)
        assert block_time3 <= 992, (slot3, block_time3)  # folga minima, nunca longe do alvo


def _self_check_enumeration_and_confirmation() -> None:
    from unittest.mock import patch

    chain = _FakeChain()
    window_start, window_end = 100, 200

    chain.add_block_signature(400, "ANCHOR_SIG_AT_200")  # slot 400 -> blockTime 200

    # Migracao valida DENTRO da janela -- deve entrar.
    chain.add_migration_tx(signature="SIG_IN_WINDOW", block_time=150, pool_mint="POOLApump")
    # Migracao com err != null -- excluida mesmo sendo CreatePool.
    chain.add_migration_tx(signature="SIG_ERRORED", block_time=160, pool_mint="POOLBpump", err={"InstructionError": []})
    # Transacao que nao e CreatePool -- excluida.
    chain.add_migration_tx(signature="SIG_NOT_CREATEPOOL", block_time=170, pool_mint="POOLCpump", is_create_pool=False)
    # Fora da janela (antes do inicio) -- nao deveria nem ser visitada.
    chain.add_migration_tx(signature="SIG_BEFORE_WINDOW", block_time=50, pool_mint="POOLDpump")
    # Fora da janela (depois do fim) -- nao deveria entrar.
    chain.add_migration_tx(signature="SIG_AFTER_WINDOW", block_time=250, pool_mint="POOLEpump")
    # Mesmo pool que SIG_IN_WINDOW, assinatura diferente -- dedup.
    chain.add_migration_tx(signature="SIG_DUP_POOL_A", block_time=155, pool_mint="POOLApump")

    with patch(
        "benchmarks.move_first_h_coverage_audit_v0.sample_migration_account._rpc", side_effect=chain.rpc
    ):
        rotator = EndpointRotator(["fake://rpc"])
        found = fetch_migrations_in_window_no_helius(rotator, window_start=window_start, window_end=window_end)

    found_mints = {c.pool_mint for c in found}
    assert found_mints == {"POOLApump"}, found_mints
    assert len(found) == 1, found  # dedup: so 1 entrada mesmo com 2 assinaturas do mesmo pool


def _self_check_parity_fixture_matches_pilot_checkpoint() -> None:
    """Nao roda rede -- so prova que PILOT_KNOWN_WINDOW/POOL_MINTS (usados
    por validate_parity_against_pilot) batem com o que sample_calendar_windows
    realmente produz pros mesmos parametros do piloto real, pra garantir que
    a validacao de paridade compara contra a janela certa."""
    from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import sample_calendar_windows

    windows = sample_calendar_windows(
        start_date="2026-07-21", end_date="2026-08-20", window_minutes=10, k=3, seed=20261008
    )
    assert PILOT_KNOWN_WINDOW in windows, (PILOT_KNOWN_WINDOW, windows)
    assert len(PILOT_KNOWN_POOL_MINTS) == 7, PILOT_KNOWN_POOL_MINTS


def _self_check() -> None:
    _self_check_binary_search()
    _self_check_enumeration_and_confirmation()
    _self_check_parity_fixture_matches_pilot_checkpoint()
    print(
        "self-check OK: busca binaria (nunca undershoot, nudge pra frente em slot pulado) + "
        "ancora+paginacao+confirmacao CreatePool (err/nao-CreatePool/fora-da-janela excluidos, "
        "dedup por pool) + fixture de paridade bate com sample_calendar_windows real"
    )


def main() -> int:
    import argparse
    import json

    from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import load_rotation_rpc_urls

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument(
        "--validate-parity",
        action="store_true",
        help="RODA REDE REAL: compara contra os 7 pool_mints conhecidos do piloto Helius",
    )
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    if args.validate_parity:
        rotator = EndpointRotator(load_rotation_rpc_urls())
        result = validate_parity_against_pilot(rotator)
        report = {
            "version": VERSION,
            "window": result.window,
            "passed": result.passed,
            "n_expected": len(result.expected_pool_mints),
            "n_found": len(result.found_pool_mints),
            "n_missing": len(result.missing),
            "n_unexpected": len(result.unexpected),
            "missing_pool_mints": sorted(result.missing),
            "unexpected_pool_mints": sorted(result.unexpected),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if result.passed else 1

    print("Nenhuma acao -- use --self-check ou --validate-parity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
