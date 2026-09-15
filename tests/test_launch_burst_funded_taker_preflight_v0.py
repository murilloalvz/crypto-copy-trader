from __future__ import annotations

import hashlib
import json
from pathlib import Path

from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft


CONTRACT_PATH = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)
BASE_FIXTURE_PATH = (
    Path("benchmarks")
    / "launch_burst_prospective_route_live_v4"
    / "funded_taker_fixture_v0.frozen.json"
)
SYNTHETIC_TAKER = "SyntheticTakerPublicKeyForOfflineFixtureTestV0"


def _fixture_for_taker(tmp_path: Path, taker: str = SYNTHETIC_TAKER) -> Path:
    fixture = json.loads(BASE_FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture["taker_public_key_sha256"] = hashlib.sha256(taker.encode("utf-8")).hexdigest()
    fixture["fixture_hash_sha256"] = ft._sha256_payload(
        {key: value for key, value in fixture.items() if key != "fixture_hash_sha256"}
    )
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _funded_balances(**_: object) -> dict[str, int]:
    return {"input_amount_raw": 25_000_000, "sol_lamports": 10_000_000}


def _assembled_probe(**kwargs: object) -> dict[str, object]:
    output_mint = str(kwargs["output_mint"])
    return {
        "router": "test-router",
        "mode": "manual",
        "transaction_present": True,
        "error_code": None,
        "error_message": None,
        "in_amount_raw": "25000000",
        "out_amount_raw": "123456",
        "in_usd_value": 25.0,
        "out_usd_value": 24.9,
        "swap_usd_value": 25.0,
        "price_impact_pct_points": 0.1,
        "observed_at": 1,
        "output_mint_for_test": output_mint,
    }


def _run(
    tmp_path: Path,
    *,
    taker: str = SYNTHETIC_TAKER,
    balance_reader=_funded_balances,
    assembly_probe=_assembled_probe,
) -> dict:
    return ft.run_preflight(
        fixture_path=_fixture_for_taker(tmp_path),
        contract_path=CONTRACT_PATH,
        rpc_url="https://example.invalid/rpc",
        jupiter_api_key="test-secret-api-key",
        taker_public_key=taker,
        balance_reader=balance_reader,
        assembly_probe=assembly_probe,
    )


def test_pass_requires_frozen_taker_funding_and_both_assembly_probes(tmp_path: Path) -> None:
    report = _run(tmp_path)
    assert report["classification"] == ft.PASS
    assert report["gates"]["taker_identity_matches_frozen_fixture"] is True
    assert report["gates"]["minimum_input_balance_met"] is True
    assert report["gates"]["minimum_sol_balance_met"] is True
    assert report["gates"]["known_liquid_control_transaction_assembled"] is True
    assert report["gates"]["representative_burst_transaction_assembled"] is True
    assert report["economic_outcomes_opened"] is False
    assert report["provider_execute_called"] is False


def test_wrong_taker_fails_before_balance_or_provider_calls(tmp_path: Path) -> None:
    calls = {"balance": 0, "probe": 0}

    def balance_reader(**_: object) -> dict[str, int]:
        calls["balance"] += 1
        return _funded_balances()

    def probe(**_: object) -> dict[str, object]:
        calls["probe"] += 1
        return _assembled_probe(output_mint="unused")

    report = _run(
        tmp_path,
        taker="DifferentSyntheticTaker",
        balance_reader=balance_reader,
        assembly_probe=probe,
    )
    assert report["classification"] == ft.FAIL
    assert report["gates"]["taker_identity_matches_frozen_fixture"] is False
    assert calls == {"balance": 0, "probe": 0}


def test_insufficient_usdc_fails_closed_before_jupiter_probe(tmp_path: Path) -> None:
    probe_calls = 0

    def balances(**_: object) -> dict[str, int]:
        return {"input_amount_raw": 24_999_999, "sol_lamports": 10_000_000}

    def probe(**_: object) -> dict[str, object]:
        nonlocal probe_calls
        probe_calls += 1
        return _assembled_probe(output_mint="unused")

    report = _run(tmp_path, balance_reader=balances, assembly_probe=probe)
    assert report["classification"] == ft.FAIL
    assert report["gates"]["minimum_input_balance_met"] is False
    assert report["gates"]["minimum_sol_balance_met"] is True
    assert report["probes"]["known_liquid_control"]["status"] == "NOT_RUN_BALANCE_GATE"
    assert report["probes"]["representative_burst"]["status"] == "NOT_RUN_BALANCE_GATE"
    assert probe_calls == 0


def test_insufficient_sol_fails_closed_before_jupiter_probe(tmp_path: Path) -> None:
    probe_calls = 0

    def balances(**_: object) -> dict[str, int]:
        return {"input_amount_raw": 25_000_000, "sol_lamports": 9_999_999}

    def probe(**_: object) -> dict[str, object]:
        nonlocal probe_calls
        probe_calls += 1
        return _assembled_probe(output_mint="unused")

    report = _run(tmp_path, balance_reader=balances, assembly_probe=probe)
    assert report["classification"] == ft.FAIL
    assert report["gates"]["minimum_input_balance_met"] is True
    assert report["gates"]["minimum_sol_balance_met"] is False
    assert probe_calls == 0


def test_known_liquid_control_without_assembled_transaction_fails(tmp_path: Path) -> None:
    def probe(**kwargs: object) -> dict[str, object]:
        result = _assembled_probe(**kwargs)
        if kwargs["output_mint"] == "So11111111111111111111111111111111111111112":
            result["transaction_present"] = False
            result["error_code"] = 1
            result["error_message"] = "Insufficient funds"
        return result

    report = _run(tmp_path, assembly_probe=probe)
    assert report["classification"] == ft.FAIL
    assert report["gates"]["known_liquid_control_transaction_assembled"] is False
    assert report["gates"]["representative_burst_transaction_assembled"] is True


def test_representative_burst_without_assembled_transaction_fails(tmp_path: Path) -> None:
    def probe(**kwargs: object) -> dict[str, object]:
        result = _assembled_probe(**kwargs)
        if kwargs["output_mint"] != "So11111111111111111111111111111111111111112":
            result["transaction_present"] = False
            result["error_code"] = 1
            result["error_message"] = "Insufficient funds"
        return result

    report = _run(tmp_path, assembly_probe=probe)
    assert report["classification"] == ft.FAIL
    assert report["gates"]["known_liquid_control_transaction_assembled"] is True
    assert report["gates"]["representative_burst_transaction_assembled"] is False


def test_report_never_contains_serialized_transaction_or_api_secret(tmp_path: Path) -> None:
    report = _run(tmp_path)
    encoded = json.dumps(report, sort_keys=True)
    assert "test-secret-api-key" not in encoded
    assert '"transaction"' not in encoded
    assert "provider_execute_called" in report
    assert report["provider_execute_called"] is False


def test_actual_frozen_fixture_matches_unchanged_route_contract() -> None:
    fixture = json.loads(BASE_FIXTURE_PATH.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    gates = ft._validate_fixture(fixture, contract)
    assert all(gates.values())
    assert contract["contract_hash_sha256"] == (
        "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"
    )
