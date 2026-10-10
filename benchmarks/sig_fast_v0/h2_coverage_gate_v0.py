"""SIG-FAST H2 Fase 3 (mandato autonomo, 2026-10-09) -- gate de cobertura
de criterios fixos.

Decide SOMENTE se Fase 4 (avaliacao economica do discovery) pode
prosseguir. NUNCA calcula nem olha nenhum retorno/EV/MFE/barreira -- so os
numeros de cobertura que seal_block/seal_discovery_block_with_stopping_rule
ja produzem. Qualquer criterio que falhar classifica o bloco inteiro
INCONCLUSIVE_SYSTEM; documentado, sem avancar pra Fase 4 (vai pra RESERVA).

Criterios (todos tem que passar):
1. Fase 1 (enumeracao sem Helius) foi validada por paridade real -- fato
   documentado (DRAFT, Addendum Fase 1), passado explicitamente aqui
   (`fase1_parity_validated`), nunca implicito nem assumido.
2. a selagem nao abortou (enumeracao/Estagio 1/Estagio 2).
3. >=90% das janelas (do k final, apos qualquer extensao da regra de
   parada) foram processadas.
4. >=95% dos buckets do Estagio 2 foram resolvidos (grade de 5s).
5. missing_source (tokens cuja propria lista de assinaturas falhou) <=5%
   das migracoes encontradas.
6. >=95% dos eventos decodificados tem reservas+fee.
7. >=30 sobreviventes no treino (so quando `require_train_survivors=True`
   -- discovery tem treino/retentor, confirmacao nao).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIN_PCT_WINDOWS_PROCESSED = 90.0
MIN_PCT_STAGE2_BUCKETS_RESOLVED = 95.0
MAX_PCT_MISSING_SOURCE = 5.0
MIN_PCT_EVENTS_WITH_RESERVES_AND_FEE = 95.0
MIN_TRAIN_SURVIVORS = 30

CLASSIFICATION_PASS = "COVERAGE_GATE_PASS"
CLASSIFICATION_FAIL = "INCONCLUSIVE_SYSTEM"


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    value: Any
    threshold: Any


@dataclass(frozen=True)
class CoverageGateResult:
    passed: bool
    classification: str
    checks: tuple[GateCheck, ...]


def _pct_windows_processed(report: dict[str, Any], *, checkpoint_path: Path) -> float:
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    n_done = len(checkpoint.get("windows_done", []))
    k_final = report.get("stopping_rule", {}).get("k_windows_final", report["k_windows"])
    if k_final <= 0:
        return 0.0
    return 100.0 * n_done / k_final


def _pct_missing_source(report: dict[str, Any]) -> float:
    n_found = report["n_migrations_found"]
    if n_found <= 0:
        return 0.0
    return 100.0 * report["n_tokens_system_error_missing"] / n_found


def evaluate_coverage_gate(
    report: dict[str, Any],
    *,
    checkpoint_path: Path,
    fase1_parity_validated: bool,
    require_train_survivors: bool = True,
    min_pct_windows_processed: float = MIN_PCT_WINDOWS_PROCESSED,
    min_pct_stage2_buckets_resolved: float = MIN_PCT_STAGE2_BUCKETS_RESOLVED,
    max_pct_missing_source: float = MAX_PCT_MISSING_SOURCE,
    min_pct_events_with_reserves_and_fee: float = MIN_PCT_EVENTS_WITH_RESERVES_AND_FEE,
    min_train_survivors: int = MIN_TRAIN_SURVIVORS,
) -> CoverageGateResult:
    """Fase 3: TODOS os criterios tem que passar. `report` e o dict que
    seal_block/seal_discovery_block_with_stopping_rule devolve. Qualquer
    falha -> classification=INCONCLUSIVE_SYSTEM, nunca calcula retorno."""
    pct_windows = _pct_windows_processed(report, checkpoint_path=checkpoint_path)
    pct_missing = _pct_missing_source(report)

    checks = [
        GateCheck("fase1_parity_validated", fase1_parity_validated is True, fase1_parity_validated, True),
        GateCheck("not_aborted", report["aborted"] is False, report["aborted"], False),
        GateCheck(
            "pct_windows_processed",
            pct_windows >= min_pct_windows_processed,
            round(pct_windows, 2),
            min_pct_windows_processed,
        ),
        GateCheck(
            "pct_stage2_buckets_resolved",
            report["avg_pct_buckets_resolved_stage2"] >= min_pct_stage2_buckets_resolved,
            report["avg_pct_buckets_resolved_stage2"],
            min_pct_stage2_buckets_resolved,
        ),
        GateCheck(
            "pct_missing_source",
            pct_missing <= max_pct_missing_source,
            round(pct_missing, 2),
            max_pct_missing_source,
        ),
        GateCheck(
            "pct_events_with_reserves_and_fee",
            report["avg_pct_decoded_with_reserves_and_fee"] >= min_pct_events_with_reserves_and_fee,
            report["avg_pct_decoded_with_reserves_and_fee"],
            min_pct_events_with_reserves_and_fee,
        ),
    ]
    if require_train_survivors:
        n_train_survivors = report.get("stopping_rule", {}).get("n_train_survivors_final")
        checks.append(
            GateCheck(
                "n_train_survivors",
                n_train_survivors is not None and n_train_survivors >= min_train_survivors,
                n_train_survivors,
                min_train_survivors,
            )
        )

    all_passed = all(c.passed for c in checks)
    return CoverageGateResult(
        passed=all_passed,
        classification=CLASSIFICATION_PASS if all_passed else CLASSIFICATION_FAIL,
        checks=tuple(checks),
    )


def gate_result_to_dict(result: CoverageGateResult) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "classification": result.classification,
        "checks": [
            {"name": c.name, "passed": c.passed, "value": c.value, "threshold": c.threshold} for c in result.checks
        ],
    }


# ------------------------------ self-checks ---------------------------------


def _base_report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "aborted": False,
        "k_windows": 26,
        "n_migrations_found": 100,
        "n_tokens_system_error_missing": 2,
        "avg_pct_buckets_resolved_stage2": 97.0,
        "avg_pct_decoded_with_reserves_and_fee": 98.0,
        "stopping_rule": {"k_windows_final": 26, "n_train_survivors_final": 40},
    }
    report.update(overrides)
    return report


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        checkpoint_path = Path(tmp) / "checkpoint.json"
        checkpoint_path.write_text(json.dumps({"windows_done": [[0, 1]] * 26}), encoding="utf-8")

        # Caso feliz: tudo passa.
        result = evaluate_coverage_gate(_base_report(), checkpoint_path=checkpoint_path, fase1_parity_validated=True)
        assert result.passed is True, result
        assert result.classification == CLASSIFICATION_PASS, result
        assert all(c.passed for c in result.checks), result.checks

        # Paridade da Fase 1 nunca assumida -- se nao passada como True, reprova.
        result = evaluate_coverage_gate(_base_report(), checkpoint_path=checkpoint_path, fase1_parity_validated=False)
        assert result.passed is False, result
        assert result.classification == CLASSIFICATION_FAIL, result
        failed_names = {c.name for c in result.checks if not c.passed}
        assert failed_names == {"fase1_parity_validated"}, failed_names

        # Abortou -> reprova mesmo que os outros numeros estejam bons.
        result = evaluate_coverage_gate(
            _base_report(aborted=True), checkpoint_path=checkpoint_path, fase1_parity_validated=True
        )
        assert result.passed is False, result
        assert {c.name for c in result.checks if not c.passed} == {"not_aborted"}

        # Estagio 2 abaixo de 95% resolvido -> reprova so esse criterio.
        result = evaluate_coverage_gate(
            _base_report(avg_pct_buckets_resolved_stage2=80.0),
            checkpoint_path=checkpoint_path,
            fase1_parity_validated=True,
        )
        assert {c.name for c in result.checks if not c.passed} == {"pct_stage2_buckets_resolved"}

        # missing_source > 5% -> reprova.
        result = evaluate_coverage_gate(
            _base_report(n_tokens_system_error_missing=10),  # 10/100 = 10% > 5%
            checkpoint_path=checkpoint_path,
            fase1_parity_validated=True,
        )
        assert {c.name for c in result.checks if not c.passed} == {"pct_missing_source"}

        # reservas+fee abaixo de 95% -> reprova.
        result = evaluate_coverage_gate(
            _base_report(avg_pct_decoded_with_reserves_and_fee=90.0),
            checkpoint_path=checkpoint_path,
            fase1_parity_validated=True,
        )
        assert {c.name for c in result.checks if not c.passed} == {"pct_events_with_reserves_and_fee"}

        # sobreviventes no treino < 30 -> reprova (mesmo que a regra de
        # parada tenha esgotado as extensoes sem atingir o alvo de 36).
        # k_windows_final fica igual ao da fixture base (26) de proposito --
        # so o numero de sobreviventes muda, pra isolar exatamente este
        # criterio (um k_windows_final diferente mexeria tambem em
        # pct_windows_processed, que usa o mesmo checkpoint de 26 janelas).
        result = evaluate_coverage_gate(
            _base_report(stopping_rule={"k_windows_final": 26, "n_train_survivors_final": 15}),
            checkpoint_path=checkpoint_path,
            fase1_parity_validated=True,
        )
        assert {c.name for c in result.checks if not c.passed} == {"n_train_survivors"}

        # confirmacao (sem treino/retentor): require_train_survivors=False
        # ignora esse criterio completamente, mesmo sem stopping_rule no report.
        confirmation_report = _base_report()
        del confirmation_report["stopping_rule"]
        result = evaluate_coverage_gate(
            confirmation_report,
            checkpoint_path=checkpoint_path,
            fase1_parity_validated=True,
            require_train_survivors=False,
        )
        assert result.passed is True, result
        assert "n_train_survivors" not in {c.name for c in result.checks}

        # <90% das janelas processadas -> reprova.
        checkpoint_path.write_text(json.dumps({"windows_done": [[0, 1]] * 20}), encoding="utf-8")  # 20/26 ~ 76.9%
        result = evaluate_coverage_gate(_base_report(), checkpoint_path=checkpoint_path, fase1_parity_validated=True)
        assert {c.name for c in result.checks if not c.passed} == {"pct_windows_processed"}

        # valor EXATAMENTE no limiar -> passa (todas as comparacoes sao
        # inclusivas, >=/<=, nunca estritas) -- prova que nenhum criterio
        # exige folga implicita alem do limiar documentado.
        checkpoint_path.write_text(json.dumps({"windows_done": [[0, 1]] * 18}), encoding="utf-8")  # 18/20 = 90.0%
        boundary_report = _base_report(
            n_migrations_found=100,
            n_tokens_system_error_missing=5,  # 5/100 = 5.0% == limite
            avg_pct_buckets_resolved_stage2=95.0,  # == limite
            avg_pct_decoded_with_reserves_and_fee=95.0,  # == limite
            stopping_rule={"k_windows_final": 20, "n_train_survivors_final": 30},  # == limite
        )
        result = evaluate_coverage_gate(boundary_report, checkpoint_path=checkpoint_path, fase1_parity_validated=True)
        assert result.passed is True, result.checks
        assert result.classification == CLASSIFICATION_PASS

        # multiplas falhas simultaneas -> todas aparecem, all() nao mascara
        # nenhuma (o relatorio real de H2 so teve 2 dos 7 criterios falhando
        # ao mesmo tempo -- este caso prova que o gate reporta os dois, nao
        # so o primeiro que encontra).
        checkpoint_path.write_text(json.dumps({"windows_done": [[0, 1]] * 26}), encoding="utf-8")
        result = evaluate_coverage_gate(
            _base_report(avg_pct_buckets_resolved_stage2=44.76, avg_pct_decoded_with_reserves_and_fee=59.41),
            checkpoint_path=checkpoint_path,
            fase1_parity_validated=True,
        )
        assert result.passed is False
        assert {c.name for c in result.checks if not c.passed} == {
            "pct_stage2_buckets_resolved",
            "pct_events_with_reserves_and_fee",
        }

        # serializacao pra JSON (coverage_report) nao perde nenhum campo.
        as_dict = gate_result_to_dict(result)
        assert as_dict["passed"] is False
        assert as_dict["classification"] == CLASSIFICATION_FAIL
        assert any(c["name"] == "pct_stage2_buckets_resolved" and not c["passed"] for c in as_dict["checks"])
        assert any(c["name"] == "pct_events_with_reserves_and_fee" and not c["passed"] for c in as_dict["checks"])
        json.dumps(as_dict)  # nunca falha a serializar

    print(
        "self-check OK: gate de cobertura (feliz=PASS; cada criterio reprova isolado: paridade, "
        "aborted, janelas processadas, buckets Estagio 2, missing_source, reservas+fee, "
        "sobreviventes no treino; confirmacao sem treino ignora esse criterio; valor exatamente "
        "no limiar passa (comparacao inclusiva); duas falhas simultaneas aparecem as duas; "
        "serializa pra JSON)"
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return 0
    print("Modulo de avaliacao -- sem entrypoint de producao proprio (chamado pelos wrappers apos a selagem).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
