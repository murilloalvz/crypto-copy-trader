"""SIG-FAST H2 Fase 5 (mandato autonomo, 2026-10-09) -- confirmacao, SO
se Fase 4 produziu CANDIDATE.

Roda a MESMA avaliacao, exatamente uma vez, no bloco de CONFIRMACAO
selado -- usando a saida JA ESCOLHIDA pela Fase 4 (nunca reescolhe). Sem
treino/retentor (confirmacao e julgada de uma vez so, nao tem split).
PASS = (a) edge de barreira (sinal-baseline) >=10pp E (b) EV liquido>0 e
PF>1 pra saida congelada. FAIL fecha H2 -- sem retune.

ANTES de abrir o bloco de confirmacao: `freeze_evaluation_rule` grava um
manifesto com hash do codigo de avaliacao (h2_discovery_evaluation_v0.py)
+ os parametros congelados + a saida escolhida -- prova de que nada foi
mudado depois de ver o resultado da confirmacao. `run_confirmation_evaluation`
RECUSA rodar (`ConfirmationNotFrozenError`) se esse manifesto nao existir
ainda -- fail-closed, nunca deixa abrir o bloco sem o commit do
congelamento feito primeiro.

Reporta (diagnostico, NUNCA decide `classification`) a sensibilidade de
custo 2x: a mesma avaliacao, com fee/terminal/rede dobrados.

NUNCA importa nem referencia nada do bloco de discovery -- so recebe
caminhos do bloco de confirmacao, explicitamente, como parametro.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from benchmarks.sig_fast_v0.h2_discovery_evaluation_v0 import (
    ATA_FEE_SOL,
    ENTRY_LATENCY_SECONDS,
    EXIT_LATENCY_SECONDS,
    MIN_EDGE_PP,
    NETWORK_FEE_SOL,
    PRIMARY_WINDOW_SECONDS,
    SIGNAL_MARKER_SECONDS,
    SIZE_SOL,
    TERMINAL_FEE_PCT,
    TokenEvaluation,
    barrier_up_rate,
    compute_exit_ev,
    evaluate_token,
    load_token_price_data,
)

VERSION = "sig_fast_h2_confirmation_evaluation_v0"
EVALUATION_MODULE_PATH = Path(__file__).parent / "h2_discovery_evaluation_v0.py"
COST_SENSITIVITY_MULTIPLIER = 2.0

CLASSIFICATION_PASS = "PASS_AGUARDA_PAPER_AO_VIVO"
CLASSIFICATION_FAIL = "FAIL"


class ConfirmationNotFrozenError(RuntimeError):
    """Fail-closed: nunca deixa abrir o bloco de confirmacao sem o
    congelamento (freeze_evaluation_rule) ja commitado primeiro."""


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class FrozenEvaluationRule:
    chosen_exit_rule: str
    evaluation_module_sha256: str
    frozen_at: int
    frozen_params: dict[str, Any]


def freeze_evaluation_rule(*, chosen_exit_rule: str, manifest_path: Path) -> FrozenEvaluationRule:
    """Fase 5: commit da regra ANTES de abrir o bloco de confirmacao.
    Nunca sobrescreve um manifesto ja existente (RuntimeError) -- um
    congelamento e definitivo, mudar a saida escolhida depois de ja ter
    congelado seria exatamente o retune que este passo existe pra
    impedir."""
    if manifest_path.exists():
        raise RuntimeError(
            f"manifesto de congelamento ja existe em {manifest_path} -- nunca sobrescrever "
            "(congelamento e definitivo; se precisar mudar, e uma rodada nova com caminho novo)"
        )
    rule = FrozenEvaluationRule(
        chosen_exit_rule=chosen_exit_rule,
        evaluation_module_sha256=_hash_file(EVALUATION_MODULE_PATH),
        frozen_at=int(time.time()),
        frozen_params={
            "entry_latency_seconds": ENTRY_LATENCY_SECONDS,
            "exit_latency_seconds": EXIT_LATENCY_SECONDS,
            "size_sol": SIZE_SOL,
            "terminal_fee_pct": TERMINAL_FEE_PCT,
            "network_fee_sol": NETWORK_FEE_SOL,
            "ata_fee_sol": ATA_FEE_SOL,
            "window_seconds": PRIMARY_WINDOW_SECONDS,
            "signal_marker_seconds": SIGNAL_MARKER_SECONDS,
            "min_edge_pp": MIN_EDGE_PP,
        },
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(asdict(rule), indent=2, sort_keys=True), encoding="utf-8")
    return rule


def load_frozen_evaluation_rule(manifest_path: Path) -> FrozenEvaluationRule:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return FrozenEvaluationRule(**data)


@dataclass(frozen=True)
class ConfirmationResult:
    classification: str
    chosen_exit_rule: str
    edge_pp: float
    net_ev_pct: float
    profit_factor: float | None
    n_signal: int
    n_baseline: int
    criterion_a_edge_ge_10pp: bool
    criterion_b_ev_pos_pf_gt1: bool
    cost_sensitivity_2x_net_ev_pct: float
    cost_sensitivity_2x_profit_factor: float | None
    cost_sensitivity_2x_still_positive: bool


def evaluate_confirmation(
    *,
    signal_evaluations: list[TokenEvaluation],
    baseline_evaluations: list[TokenEvaluation],
    chosen_exit_rule: str,
    signal_evaluations_2x_cost: list[TokenEvaluation],
    min_edge_pp: float = MIN_EDGE_PP,
) -> ConfirmationResult:
    signal_rate, _, _ = barrier_up_rate(signal_evaluations)
    baseline_rate, _, _ = barrier_up_rate(baseline_evaluations)
    edge_pp = (signal_rate - baseline_rate) * 100.0
    criterion_a = edge_pp >= min_edge_pp

    ev = compute_exit_ev(signal_evaluations, rule_id=chosen_exit_rule)
    criterion_b = ev.net_ev_pct > 0 and ev.profit_factor is not None and ev.profit_factor > 1

    ev_2x = compute_exit_ev(signal_evaluations_2x_cost, rule_id=chosen_exit_rule)
    cost_sensitivity_still_positive = (
        ev_2x.net_ev_pct > 0 and ev_2x.profit_factor is not None and ev_2x.profit_factor > 1
    )

    passed = criterion_a and criterion_b
    return ConfirmationResult(
        classification=CLASSIFICATION_PASS if passed else CLASSIFICATION_FAIL,
        chosen_exit_rule=chosen_exit_rule,
        edge_pp=edge_pp,
        net_ev_pct=ev.net_ev_pct,
        profit_factor=ev.profit_factor,
        n_signal=len(signal_evaluations),
        n_baseline=len(baseline_evaluations),
        criterion_a_edge_ge_10pp=criterion_a,
        criterion_b_ev_pos_pf_gt1=criterion_b,
        cost_sensitivity_2x_net_ev_pct=ev_2x.net_ev_pct,
        cost_sensitivity_2x_profit_factor=ev_2x.profit_factor,
        cost_sensitivity_2x_still_positive=cost_sensitivity_still_positive,
    )


def run_confirmation_evaluation(
    *, db_path: Path, checkpoint_path: Path, coverage_report_path: Path, manifest_path: Path
) -> ConfirmationResult:
    """Fase 5: SO roda se manifest_path ja existir (congelado ANTES desta
    chamada abrir o banco) -- `db_path`/`checkpoint_path`/
    `coverage_report_path` tem que ser os do bloco de CONFIRMACAO; este
    modulo nao sabe nem precisa saber onde fica o bloco de discovery."""
    if not manifest_path.exists():
        raise ConfirmationNotFrozenError(
            f"manifesto de congelamento nao existe ainda ({manifest_path}) -- chame "
            "freeze_evaluation_rule ANTES de abrir o bloco de confirmacao"
        )
    frozen = load_frozen_evaluation_rule(manifest_path)

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    coverage_report = json.loads(coverage_report_path.read_text(encoding="utf-8"))
    stage1 = checkpoint["stage1"]
    baseline_pools = set(coverage_report["baseline_pools"])
    survivor_pools = {p for p, r in stage1.items() if r["survived_20min_system_count"] is True}

    conn = sqlite3.connect(str(db_path))
    try:
        signal_data = [(pool, load_token_price_data(conn, pool)) for pool in sorted(survivor_pools)]
        baseline_data = [(pool, load_token_price_data(conn, pool)) for pool in sorted(baseline_pools)]
    finally:
        conn.close()

    signal_evaluations = [
        evaluate_token(data, migration_block_time=stage1[pool]["migration_block_time"], group="signal")
        for pool, data in signal_data
    ]
    baseline_evaluations = [
        evaluate_token(data, migration_block_time=stage1[pool]["migration_block_time"], group="baseline")
        for pool, data in baseline_data
    ]
    signal_evaluations_2x = [
        evaluate_token(
            data,
            migration_block_time=stage1[pool]["migration_block_time"],
            group="signal",
            cost_multiplier=COST_SENSITIVITY_MULTIPLIER,
        )
        for pool, data in signal_data
    ]

    return evaluate_confirmation(
        signal_evaluations=signal_evaluations,
        baseline_evaluations=baseline_evaluations,
        chosen_exit_rule=frozen.chosen_exit_rule,
        signal_evaluations_2x_cost=signal_evaluations_2x,
    )


def result_to_dict(result: ConfirmationResult) -> dict[str, Any]:
    return {
        "version": VERSION,
        "classification": result.classification,
        "chosen_exit_rule": result.chosen_exit_rule,
        "edge_pp": round(result.edge_pp, 2),
        "net_ev_pct": round(result.net_ev_pct, 4),
        "profit_factor": result.profit_factor,
        "n_signal": result.n_signal,
        "n_baseline": result.n_baseline,
        "criterion_a_edge_ge_10pp": result.criterion_a_edge_ge_10pp,
        "criterion_b_ev_pos_pf_gt1": result.criterion_b_ev_pos_pf_gt1,
        "cost_sensitivity_2x_net_ev_pct": round(result.cost_sensitivity_2x_net_ev_pct, 4),
        "cost_sensitivity_2x_profit_factor": result.cost_sensitivity_2x_profit_factor,
        "cost_sensitivity_2x_still_positive_diagnostic_only": result.cost_sensitivity_2x_still_positive,
    }


# ------------------------------ self-checks ---------------------------------


def _self_check_freeze_guard() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        manifest_path = Path(tmp) / "frozen_rule.json"

        # Sem congelamento ainda -- recusa rodar (fail-closed).
        try:
            run_confirmation_evaluation(
                db_path=Path(tmp) / "nope.db",
                checkpoint_path=Path(tmp) / "nope_checkpoint.json",
                coverage_report_path=Path(tmp) / "nope_report.json",
                manifest_path=manifest_path,
            )
            raise AssertionError("deveria ter recusado sem o manifesto congelado")
        except ConfirmationNotFrozenError:
            pass

        frozen = freeze_evaluation_rule(chosen_exit_rule="tp50_sl30_v0", manifest_path=manifest_path)
        assert frozen.chosen_exit_rule == "tp50_sl30_v0", frozen
        assert len(frozen.evaluation_module_sha256) == 64, frozen  # sha256 hex
        assert frozen.evaluation_module_sha256 == _hash_file(EVALUATION_MODULE_PATH), frozen
        assert manifest_path.exists(), "manifesto deveria ter sido gravado"

        reloaded = load_frozen_evaluation_rule(manifest_path)
        assert reloaded == frozen, (reloaded, frozen)

        # Congelamento e definitivo -- nunca sobrescreve.
        try:
            freeze_evaluation_rule(chosen_exit_rule="tp100_sl50_v0", manifest_path=manifest_path)
            raise AssertionError("deveria ter recusado sobrescrever um manifesto ja congelado")
        except RuntimeError as exc:
            assert "ja existe" in str(exc), exc


def _self_check_evaluate_confirmation() -> None:
    """Cenario calculavel a mao: edge forte + EV positivo com custo
    normal, mas a sensibilidade de custo 2x derruba o PF (diagnostico,
    nunca muda a classification, que fica PASS de qualquer jeito)."""
    from benchmarks.sig_fast_v0.h2_discovery_evaluation_v0 import ExitResult

    def _ev(pool: str, barrier: str, net_return: float | None) -> TokenEvaluation:
        return TokenEvaluation(
            pool_mint=pool,
            group="signal",
            signal_time=0,
            missing_reason=None,
            barrier_outcome=barrier,
            exit_results={
                "tp50_sl30_v0": ExitResult(
                    rule_id="tp50_sl30_v0",
                    exit_latency_seconds=32,
                    trigger_chain_time=10 if net_return is not None else None,
                    exit_chain_time=20 if net_return is not None else None,
                    exit_reason="fake",
                    gross_return_pct=net_return,
                    net_return_pct=net_return,
                    missing_reason=None,
                )
            },
            window_metrics_diagnostic=None,
        )

    signal = [_ev("S0", "UP", 40.0), _ev("S1", "UP", 40.0), _ev("S2", "UP", -10.0)]
    baseline = [_ev("B0", "DOWN", None), _ev("B1", "DOWN", None), _ev("B2", "UP", None)]
    # Custo 2x: so pra prova do self-check (nao vem de evaluate_token
    # aqui), finge que o PF cai abaixo de 1 com o dobro do custo.
    signal_2x = [_ev("S0", "UP", 5.0), _ev("S1", "UP", 5.0), _ev("S2", "UP", -10.0)]

    result = evaluate_confirmation(
        signal_evaluations=signal,
        baseline_evaluations=baseline,
        chosen_exit_rule="tp50_sl30_v0",
        signal_evaluations_2x_cost=signal_2x,
    )
    assert result.n_signal == 3 and result.n_baseline == 3, result
    # sinal 3/3 UP (S2 bate a barreira UP mas a SAIDA especifica ainda da
    # -10% -- barreira e saida sao caminhos de calculo independentes no
    # F2, podem divergir); baseline 1/3 UP.
    assert result.edge_pp == (1.0 - 1 / 3) * 100.0, result
    assert result.criterion_a_edge_ge_10pp is True, result
    assert round(result.net_ev_pct, 2) == round((40 + 40 - 10) / 3, 2), result
    assert result.profit_factor == 8.0, result  # gross_profit=80, gross_loss=10
    assert result.criterion_b_ev_pos_pf_gt1 is True, result
    assert result.classification == CLASSIFICATION_PASS, result
    # custo 2x: gross_profit=10, gross_loss=10 -> PF=1.0, nao > 1 -- fica
    # False, mas NUNCA muda a classification (so diagnostico).
    assert result.cost_sensitivity_2x_profit_factor == 1.0, result
    assert result.cost_sensitivity_2x_still_positive is False, result
    assert result.classification == CLASSIFICATION_PASS, "custo 2x nunca decide o PASS/FAIL"


def _self_check() -> None:
    _self_check_freeze_guard()
    _self_check_evaluate_confirmation()
    print(
        "self-check OK: congelamento fail-closed (recusa sem manifesto, recusa sobrescrever) + "
        "avaliacao de confirmacao (edge/EV/PF da saida congelada, sensibilidade de custo 2x "
        "sempre diagnostico, nunca decide PASS/FAIL)"
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return 0
    print("Modulo de avaliacao -- sem entrypoint de producao proprio (ver runbook da Fase 5/6).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
