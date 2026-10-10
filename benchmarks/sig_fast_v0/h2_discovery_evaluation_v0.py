"""SIG-FAST H2 Fase 4 (mandato autonomo, 2026-10-09) -- avaliacao do
discovery: a UNICA fase que decide CANDIDATE/FAIL pro lote H2 nesta
rodada.

NUNCA abre o bloco de confirmacao -- `run_discovery_evaluation` so recebe
caminhos do bloco de discovery (db_path/checkpoint_path/coverage_report_path
sao parametros explicitos, nunca um default compartilhado com
confirmacao; nao ha nenhum import de h2_seal_confirmation_v0 aqui).

Grupo de SINAL = sobreviventes (classificacao de sistema do Estagio 1, ja
selada). Grupo de BASELINE = a amostra de TODAS as migracoes classificadas
(Fase 0a, ja selada com o grid completo do Estagio 2). Ambos entram no
MESMO marcador +20min (SIGNAL_MARKER_SECONDS) -- ver Addendum Fase 0a no
DRAFT ("baseline... entrando no mesmo marcador +20min"). Delta=32s de
latencia (30s reacao + 2s deteccao, Fase 0c). Fee por pool resolvido do
evento decodificado mais proximo NO PASSADO (nunca uma tabela inventada,
Fase 0b) -- `lp_fee_basis_points_raw + coin_creator_fee_basis_points_raw +
protocol_fee_basis_points_raw`, confirmado presente nos dados reais
selados (ver DRAFT, Addendum Fase 4).

Preco/barreira/saidas reusam `src/opportunity_path_metrics_v0.py` (F2) sem
nenhuma mudanca -- confirmado em Fase 0b que F2 ja implementa exatamente
o pedido (AMM constant-product + fee contra reservas do pool).

MFE/MAE (via `compute_window_metrics`) sao reportados SO como diagnostico
-- nunca entram em `classification`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.opportunity_path_metrics_v0 import (
    EXIT_RULE_IDS,
    CostModel,
    ExitResult,
    PathTrade,
    WindowMetrics,
    compute_window_metrics,
    find_causal_entry,
    first_barrier_touch,
    simulate_exit,
)

VERSION = "sig_fast_h2_discovery_evaluation_v0"

# Fase 0c: parametros congelados (ver DRAFT, Addendum Fase 0c) -- literais
# aqui, nunca recalculados nem ajustados depois de ver retorno.
SIGNAL_MARKER_SECONDS = 20 * 60
ENTRY_LATENCY_SECONDS = 32  # 30s reacao + 2s deteccao
EXIT_LATENCY_SECONDS = 32
SIZE_SOL = 0.15
TERMINAL_FEE_PCT = 1.0
NETWORK_FEE_SOL = 0.0003
ATA_FEE_SOL = 0.0
PRIMARY_WINDOW_SECONDS = 900
BARRIER_TARGET_PCT = 50.0
BARRIER_STOP_PCT = -30.0
MIN_EDGE_PP = 10.0
TRAIN_FRACTION = 0.7

CLASSIFICATION_CANDIDATE = "CANDIDATE"
CLASSIFICATION_FAIL = "FAIL"


def _total_fee_pct(event: dict[str, Any]) -> float | None:
    """Fase 0b: soma dos 3 componentes de fee em basis points (bps/100 =
    %). Missing explicito se QUALQUER componente estiver ausente -- nunca
    assume 0 pro que falta (isso inventaria uma fee mais baixa que a real)."""
    lp = event.get("lp_fee_basis_points_raw")
    creator = event.get("coin_creator_fee_basis_points_raw")
    protocol = event.get("protocol_fee_basis_points_raw")
    if lp is None or creator is None or protocol is None:
        return None
    return (lp + creator + protocol) / 100.0


@dataclass(frozen=True)
class TokenPriceData:
    pool_mint: str
    trades: tuple[PathTrade, ...]
    fee_events: tuple[tuple[int, float], ...]  # (block_time, total_fee_pct), ordenado por block_time


def load_token_price_data(conn: sqlite3.Connection, pool_mint: str) -> TokenPriceData:
    rows = conn.execute(
        "SELECT block_time, decoded_json FROM sig_fast_h2_backfill_v0 "
        "WHERE pool_mint = ? AND decode_status = 'decoded' AND decoded_json IS NOT NULL "
        "ORDER BY block_time, fetch_sequence",
        (pool_mint,),
    ).fetchall()
    trades: list[PathTrade] = []
    fee_events: list[tuple[int, float]] = []
    for block_time, decoded_json in rows:
        event = json.loads(decoded_json)
        trades.append(
            PathTrade(
                chain_time=block_time,
                venue="pumpswap",
                base_amount_raw=event.get("base_amount_raw"),
                quote_amount_raw=event.get("quote_amount_raw"),
                base_reserves_raw=event.get("pool_base_token_reserves_raw"),
                quote_reserves_raw=event.get("pool_quote_token_reserves_raw"),
            )
        )
        fee_pct = _total_fee_pct(event)
        if fee_pct is not None:
            fee_events.append((block_time, fee_pct))
    return TokenPriceData(pool_mint=pool_mint, trades=tuple(trades), fee_events=tuple(fee_events))


def resolve_fee_pct_at(fee_events: tuple[tuple[int, float], ...], *, at_time: int) -> float | None:
    """Fase 0b: fee do evento decodificado mais recente NO PASSADO (causal
    -- nunca olha pra frente); se nenhum evento <= at_time tiver fee, cai
    pro primeiro disponivel do pool (raro, pool com atividade so depois do
    marcador); None (missing explicito) se o pool nao tiver NENHUM evento
    com fee -- nunca um valor global inventado."""
    past = [fp for bt, fp in fee_events if bt <= at_time]
    if past:
        return past[-1]
    if fee_events:
        return fee_events[0][1]
    return None


@dataclass(frozen=True)
class TokenEvaluation:
    pool_mint: str
    group: str  # "signal" ou "baseline"
    signal_time: int
    missing_reason: str | None
    barrier_outcome: str | None  # "UP"/"DOWN"/"NONE" -- None so se missing
    exit_results: dict[str, ExitResult]
    window_metrics_diagnostic: WindowMetrics | None  # MFE/MAE -- NUNCA decisorio


def evaluate_token(
    data: TokenPriceData,
    *,
    migration_block_time: int,
    group: str,
    window_seconds: int = PRIMARY_WINDOW_SECONDS,
    cost_multiplier: float = 1.0,
) -> TokenEvaluation:
    """`cost_multiplier` existe SO pro diagnostico de sensibilidade de
    custo 2x da Fase 5 (`docs`, "sensibilidade de custo 2x") -- escala
    fee/terminal/rede igualmente, nunca decisorio por si so (Fase 4/5
    tratam isso como diagnostico, nunca como criterio de PASS/FAIL).
    Default 1.0 preserva o comportamento exato de antes desta opcao."""
    signal_time = migration_block_time + SIGNAL_MARKER_SECONDS
    fee_pct = resolve_fee_pct_at(data.fee_events, at_time=signal_time)
    if fee_pct is None:
        return TokenEvaluation(
            pool_mint=data.pool_mint,
            group=group,
            signal_time=signal_time,
            missing_reason="no_fee_data",
            barrier_outcome=None,
            exit_results={},
            window_metrics_diagnostic=None,
        )
    cost_model = CostModel(
        venue_fee_pct=fee_pct * cost_multiplier,
        terminal_fee_pct=TERMINAL_FEE_PCT * cost_multiplier,
        network_fee_sol=NETWORK_FEE_SOL * cost_multiplier,
        ata_fee_sol=ATA_FEE_SOL * cost_multiplier,
    )
    entry = find_causal_entry(
        data.trades,
        signal_time=signal_time,
        entry_latency_seconds=ENTRY_LATENCY_SECONDS,
        size_sol=SIZE_SOL,
        cost_model=cost_model,
    )
    if entry.trade_chain_time is None or entry.execution_price_sol is None:
        return TokenEvaluation(
            pool_mint=data.pool_mint,
            group=group,
            signal_time=signal_time,
            missing_reason=entry.missing_reason or "no_entry",
            barrier_outcome=None,
            exit_results={},
            window_metrics_diagnostic=None,
        )
    barrier = first_barrier_touch(
        data.trades,
        entry_chain_time=entry.trade_chain_time,
        entry_execution_price_sol=entry.execution_price_sol,
        window_seconds=window_seconds,
        target_pct=BARRIER_TARGET_PCT,
        stop_pct=BARRIER_STOP_PCT,
    )
    exit_results = {
        rule_id: simulate_exit(
            data.trades,
            rule_id=rule_id,
            entry_chain_time=entry.trade_chain_time,
            entry_execution_price_sol=entry.execution_price_sol,
            size_sol=SIZE_SOL,
            window_seconds=window_seconds,
            exit_latency_seconds=EXIT_LATENCY_SECONDS,
            cost_model=cost_model,
        )
        for rule_id in EXIT_RULE_IDS
    }
    window_metrics = compute_window_metrics(
        data.trades,
        entry_chain_time=entry.trade_chain_time,
        entry_execution_price_sol=entry.execution_price_sol,
        window_seconds=window_seconds,
    )
    return TokenEvaluation(
        pool_mint=data.pool_mint,
        group=group,
        signal_time=signal_time,
        missing_reason=None,
        barrier_outcome=barrier,
        exit_results=exit_results,
        window_metrics_diagnostic=window_metrics,
    )


def barrier_up_rate(evaluations: list[TokenEvaluation]) -> tuple[float, int, int]:
    """(P(UP), n_determinavel, n_total) -- missing excluido do numerador E
    do denominador (nunca tratado como sucesso nem como fracasso)."""
    determinable = [e for e in evaluations if e.barrier_outcome is not None]
    n_up = sum(1 for e in determinable if e.barrier_outcome == "UP")
    rate = (n_up / len(determinable)) if determinable else 0.0
    return rate, len(determinable), len(evaluations)


@dataclass(frozen=True)
class ExitRuleEV:
    rule_id: str
    n_determinable: int
    net_ev_pct: float
    profit_factor: float | None  # None se gross_loss==0 (indefinido, nunca inf fingido)


def compute_exit_ev(evaluations: list[TokenEvaluation], *, rule_id: str) -> ExitRuleEV:
    returns = [
        e.exit_results[rule_id].net_return_pct
        for e in evaluations
        if rule_id in e.exit_results and e.exit_results[rule_id].net_return_pct is not None
    ]
    if not returns:
        return ExitRuleEV(rule_id=rule_id, n_determinable=0, net_ev_pct=0.0, profit_factor=None)
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = -sum(r for r in returns if r < 0)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    return ExitRuleEV(
        rule_id=rule_id,
        n_determinable=len(returns),
        net_ev_pct=sum(returns) / len(returns),
        profit_factor=profit_factor,
    )


def select_best_exit_rule(evaluations: list[TokenEvaluation]) -> ExitRuleEV:
    """Fase 4(b): escolhe NO TREINO a melhor das 6 saidas fixas por EV
    liquido medio."""
    candidates = [compute_exit_ev(evaluations, rule_id=rule_id) for rule_id in EXIT_RULE_IDS]
    return max(candidates, key=lambda c: c.net_ev_pct)


@dataclass(frozen=True)
class DiscoveryEvaluationResult:
    classification: str
    chosen_exit_rule: str
    train_edge_pp: float
    train_net_ev_pct: float
    train_profit_factor: float | None
    holdout_edge_pp: float
    holdout_net_ev_pct: float
    holdout_profit_factor: float | None
    n_signal_train: int
    n_baseline_train: int
    n_signal_holdout: int
    n_baseline_holdout: int
    criterion_a_train: bool
    criterion_b_train: bool
    criterion_a_holdout: bool
    criterion_b_holdout: bool


def evaluate_discovery(
    *,
    signal_evaluations: list[TokenEvaluation],
    baseline_evaluations: list[TokenEvaluation],
    train_cutoff: int,
    min_edge_pp: float = MIN_EDGE_PP,
) -> DiscoveryEvaluationResult:
    """Fase 4: (a) edge de barreira (sinal - baseline) >=10pp; (b) melhor
    saida por EV no TREINO, exige EV>0 E PF>1; (c) no RETENTOR, a MESMA
    saida escolhida revalida (a) e (b). CANDIDATE so se TODOS valerem;
    senao FAIL. Nunca reescolhe a saida no retentor -- (c) e so
    confirmacao, nao uma nova selecao (evitaria exatamente o retune que o
    desenho treino/retentor existe pra prevenir)."""
    signal_train = [e for e in signal_evaluations if e.signal_time < train_cutoff]
    signal_holdout = [e for e in signal_evaluations if e.signal_time >= train_cutoff]
    baseline_train = [e for e in baseline_evaluations if e.signal_time < train_cutoff]
    baseline_holdout = [e for e in baseline_evaluations if e.signal_time >= train_cutoff]

    signal_rate_train, _, _ = barrier_up_rate(signal_train)
    baseline_rate_train, _, _ = barrier_up_rate(baseline_train)
    train_edge_pp = (signal_rate_train - baseline_rate_train) * 100.0
    criterion_a_train = train_edge_pp >= min_edge_pp

    best = select_best_exit_rule(signal_train)
    criterion_b_train = (
        best.net_ev_pct > 0 and best.profit_factor is not None and best.profit_factor > 1
    )

    signal_rate_holdout, _, _ = barrier_up_rate(signal_holdout)
    baseline_rate_holdout, _, _ = barrier_up_rate(baseline_holdout)
    holdout_edge_pp = (signal_rate_holdout - baseline_rate_holdout) * 100.0
    criterion_a_holdout = holdout_edge_pp >= min_edge_pp

    holdout_ev = compute_exit_ev(signal_holdout, rule_id=best.rule_id)
    criterion_b_holdout = (
        holdout_ev.net_ev_pct > 0 and holdout_ev.profit_factor is not None and holdout_ev.profit_factor > 1
    )

    candidate = criterion_a_train and criterion_b_train and criterion_a_holdout and criterion_b_holdout
    return DiscoveryEvaluationResult(
        classification=CLASSIFICATION_CANDIDATE if candidate else CLASSIFICATION_FAIL,
        chosen_exit_rule=best.rule_id,
        train_edge_pp=train_edge_pp,
        train_net_ev_pct=best.net_ev_pct,
        train_profit_factor=best.profit_factor,
        holdout_edge_pp=holdout_edge_pp,
        holdout_net_ev_pct=holdout_ev.net_ev_pct,
        holdout_profit_factor=holdout_ev.profit_factor,
        n_signal_train=len(signal_train),
        n_baseline_train=len(baseline_train),
        n_signal_holdout=len(signal_holdout),
        n_baseline_holdout=len(baseline_holdout),
        criterion_a_train=criterion_a_train,
        criterion_b_train=criterion_b_train,
        criterion_a_holdout=criterion_a_holdout,
        criterion_b_holdout=criterion_b_holdout,
    )


def _train_cutoff_from_report(coverage_report: dict[str, Any]) -> int:
    stopping_rule = coverage_report.get("stopping_rule") or {}
    cutoff = stopping_rule.get("train_cutoff_epoch")
    if cutoff is not None:
        return cutoff
    from datetime import datetime, timezone

    start_epoch = int(
        datetime.strptime(coverage_report["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    )
    end_epoch = int(
        datetime.strptime(coverage_report["end_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    )
    return start_epoch + int((end_epoch - start_epoch) * TRAIN_FRACTION)


def run_discovery_evaluation(
    *, db_path: Path, checkpoint_path: Path, coverage_report_path: Path
) -> DiscoveryEvaluationResult:
    """Fase 4: le SO o bloco de discovery (os 3 caminhos tem que ser do
    mesmo bloco -- este modulo nunca importa nem referencia nada de
    confirmacao). `checkpoint_path` da a classificacao de sistema
    (sobreviventes) e `coverage_report_path` da a amostra de baseline
    (Fase 0a) e o corte treino/retentor."""
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    coverage_report = json.loads(coverage_report_path.read_text(encoding="utf-8"))
    stage1 = checkpoint["stage1"]
    baseline_pools = set(coverage_report["baseline_pools"])
    survivor_pools = {p for p, r in stage1.items() if r["survived_20min_system_count"] is True}
    train_cutoff = _train_cutoff_from_report(coverage_report)

    conn = sqlite3.connect(str(db_path))
    try:
        signal_evaluations = [
            evaluate_token(
                load_token_price_data(conn, pool),
                migration_block_time=stage1[pool]["migration_block_time"],
                group="signal",
            )
            for pool in sorted(survivor_pools)
        ]
        baseline_evaluations = [
            evaluate_token(
                load_token_price_data(conn, pool),
                migration_block_time=stage1[pool]["migration_block_time"],
                group="baseline",
            )
            for pool in sorted(baseline_pools)
        ]
    finally:
        conn.close()

    return evaluate_discovery(
        signal_evaluations=signal_evaluations,
        baseline_evaluations=baseline_evaluations,
        train_cutoff=train_cutoff,
    )


def result_to_dict(result: DiscoveryEvaluationResult) -> dict[str, Any]:
    return {
        "version": VERSION,
        "classification": result.classification,
        "chosen_exit_rule": result.chosen_exit_rule,
        "train_edge_pp": round(result.train_edge_pp, 2),
        "train_net_ev_pct": round(result.train_net_ev_pct, 4),
        "train_profit_factor": result.train_profit_factor,
        "holdout_edge_pp": round(result.holdout_edge_pp, 2),
        "holdout_net_ev_pct": round(result.holdout_net_ev_pct, 4),
        "holdout_profit_factor": result.holdout_profit_factor,
        "n_signal_train": result.n_signal_train,
        "n_baseline_train": result.n_baseline_train,
        "n_signal_holdout": result.n_signal_holdout,
        "n_baseline_holdout": result.n_baseline_holdout,
        "criterion_a_train_edge_ge_10pp": result.criterion_a_train,
        "criterion_b_train_ev_pos_pf_gt1": result.criterion_b_train,
        "criterion_a_holdout_edge_ge_10pp": result.criterion_a_holdout,
        "criterion_b_holdout_ev_pos_pf_gt1": result.criterion_b_holdout,
    }


# ------------------------------ self-checks ---------------------------------


def _fake_evaluation(
    pool: str, *, signal_time: int, barrier: str | None, exit_returns: dict[str, float | None]
) -> TokenEvaluation:
    exit_results = {
        rule_id: ExitResult(
            rule_id=rule_id,
            exit_latency_seconds=EXIT_LATENCY_SECONDS,
            trigger_chain_time=signal_time + 10 if net_return is not None else None,
            exit_chain_time=signal_time + 20 if net_return is not None else None,
            exit_reason="fake" if net_return is not None else None,
            gross_return_pct=net_return,
            net_return_pct=net_return,
            missing_reason=None if net_return is not None else "fake_missing",
        )
        for rule_id, net_return in exit_returns.items()
    }
    return TokenEvaluation(
        pool_mint=pool,
        group="signal",
        signal_time=signal_time,
        missing_reason=None,
        barrier_outcome=barrier,
        exit_results=exit_results,
        window_metrics_diagnostic=None,
    )


def _self_check_fee_resolution_missingness() -> None:
    """`resolve_fee_pct_at`/`_total_fee_pct` isolados (sem banco, sem
    pipeline inteiro) -- a cobertura existente so exercita o caminho feliz
    (fee sempre presente) atraves do self-check de pipeline completo; aqui
    prova o caminho causal (olha so pro passado), o fallback pro primeiro
    evento disponivel, e o missing explicito quando o pool nao tem NENHUM
    fee -- nunca inventa 0 ou reusa fee de outro pool."""
    fee_events = ((100, 1.5), (200, 2.0), (400, 2.5))

    # exatamente no tempo de um evento -> usa esse evento (fronteira causal,
    # <=, nunca <).
    assert resolve_fee_pct_at(fee_events, at_time=200) == 2.0
    # entre dois eventos -> usa o mais recente NO PASSADO, nunca o futuro.
    assert resolve_fee_pct_at(fee_events, at_time=250) == 2.0
    assert resolve_fee_pct_at(fee_events, at_time=399) == 2.0
    # antes de qualquer evento -> cai pro primeiro disponivel (fallback raro,
    # documentado), nao None.
    assert resolve_fee_pct_at(fee_events, at_time=50) == 1.5
    # pool sem nenhum evento de fee -> None explicito, nunca 0 inventado.
    assert resolve_fee_pct_at((), at_time=200) is None

    # _total_fee_pct: qualquer um dos 3 componentes ausente -> None, nunca
    # soma so os presentes (isso subestimaria a fee real).
    assert _total_fee_pct(
        {
            "lp_fee_basis_points_raw": 25,
            "coin_creator_fee_basis_points_raw": 5,
            "protocol_fee_basis_points_raw": 20,
        }
    ) == 0.5  # (25+5+20)/100
    assert _total_fee_pct({"lp_fee_basis_points_raw": 25, "coin_creator_fee_basis_points_raw": 5}) is None
    assert _total_fee_pct({}) is None


def _self_check_aggregation() -> None:
    """Prova a logica de decisao (barrier_up_rate, compute_exit_ev,
    select_best_exit_rule, evaluate_discovery) com um cenario pequeno,
    calculavel a mao -- sem precisar de rede nem de banco."""
    train_cutoff = 1_000_000

    # EXIT_RULE_TP50_SL30 e claramente a melhor saida nos 4 tokens de sinal
    # do treino (3 ganhos de 50%, 1 perda de 20% -> media 32.5%, PF=7.5);
    # as outras 5 saidas sao uniformemente negativas (-10% cada) --
    # select_best_exit_rule tem que escolher TP50_SL30 sem ambiguidade.
    other_rules = [r for r in EXIT_RULE_IDS if r != "tp50_sl30_v0"]

    def _signal_train_token(i: int, barrier: str, tp50_return: float) -> TokenEvaluation:
        returns = {"tp50_sl30_v0": tp50_return}
        returns.update({r: -10.0 for r in other_rules})
        return _fake_evaluation(f"SIGTRAIN{i}", signal_time=train_cutoff - 1000 + i, barrier=barrier, exit_returns=returns)

    signal_train = [
        _signal_train_token(0, "UP", 50.0),
        _signal_train_token(1, "UP", 50.0),
        _signal_train_token(2, "UP", 50.0),
        _signal_train_token(3, "DOWN", -20.0),
    ]
    baseline_train = [
        _fake_evaluation(f"BASETRAIN{i}", signal_time=train_cutoff - 1000 + i, barrier=b, exit_returns={})
        for i, b in enumerate(["DOWN", "DOWN", "UP", "DOWN"])
    ]

    def _signal_holdout_token(i: int, barrier: str, tp50_return: float) -> TokenEvaluation:
        returns = {"tp50_sl30_v0": tp50_return}
        returns.update({r: -10.0 for r in other_rules})
        return _fake_evaluation(f"SIGHOLD{i}", signal_time=train_cutoff + 1000 + i, barrier=barrier, exit_returns=returns)

    signal_holdout = [
        _signal_holdout_token(0, "UP", 40.0),
        _signal_holdout_token(1, "UP", 40.0),
        _signal_holdout_token(2, "UP", 40.0),
        _signal_holdout_token(3, "UP", -10.0),
    ]
    baseline_holdout = [
        _fake_evaluation(f"BASEHOLD{i}", signal_time=train_cutoff + 1000 + i, barrier=b, exit_returns={})
        for i, b in enumerate(["DOWN", "DOWN", "DOWN", "UP"])
    ]

    result = evaluate_discovery(
        signal_evaluations=signal_train + signal_holdout,
        baseline_evaluations=baseline_train + baseline_holdout,
        train_cutoff=train_cutoff,
    )
    assert result.chosen_exit_rule == "tp50_sl30_v0", result
    assert result.n_signal_train == 4 and result.n_baseline_train == 4, result
    assert result.n_signal_holdout == 4 and result.n_baseline_holdout == 4, result
    assert result.train_edge_pp == 50.0, result  # 0.75 - 0.25 = 50pp
    assert result.criterion_a_train is True, result
    assert round(result.train_net_ev_pct, 2) == 32.5, result
    assert result.train_profit_factor == 7.5, result
    assert result.criterion_b_train is True, result
    assert result.holdout_edge_pp == 75.0, result  # 1.0 - 0.25 = 75pp
    assert result.criterion_a_holdout is True, result
    assert round(result.holdout_net_ev_pct, 2) == 27.5, result  # (40+40+40-10)/4
    assert result.holdout_profit_factor == 12.0, result  # 120/10
    assert result.criterion_b_holdout is True, result
    assert result.classification == CLASSIFICATION_CANDIDATE, result

    # Agora quebra SO o criterio (a) do retentor (baseline_holdout tao bom
    # quanto o sinal -- edge cai pra 0) -- o resto fica igual, tem que
    # virar FAIL mesmo com (a)/(b) do treino e (b) do retentor intactos.
    baseline_holdout_strong = [
        _fake_evaluation(f"BASEHOLD{i}", signal_time=train_cutoff + 1000 + i, barrier="UP", exit_returns={})
        for i in range(4)
    ]
    result2 = evaluate_discovery(
        signal_evaluations=signal_train + signal_holdout,
        baseline_evaluations=baseline_train + baseline_holdout_strong,
        train_cutoff=train_cutoff,
    )
    assert result2.criterion_a_train is True, result2
    assert result2.criterion_b_train is True, result2
    assert result2.criterion_a_holdout is False, result2  # 1.0 - 1.0 = 0pp < 10pp
    assert result2.criterion_b_holdout is True, result2
    assert result2.classification == CLASSIFICATION_FAIL, result2


def _self_check_token_pipeline_and_db_wiring() -> None:
    """Prova a cadeia inteira a partir de arquivos reais (banco SQLite +
    checkpoint.json + coverage_report.json), igual ao que
    run_discovery_evaluation vai ler de verdade -- um sobrevivente com
    preco subindo +50% depois da entrada (deveria bater a barreira UP) e
    um baseline com preco parado (nem UP nem DOWN). Reservas em escala
    realista (pool ~1000 SOL) pra um trade de 0.15 SOL dar slippage
    desprezivel -- preco de execucao fica bem perto do mid price, o que
    deixa o resultado esperado calculavel a mao."""
    import tempfile

    from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import ensure_h2_backfill_schema

    migration_block_time = 1_700_000_000
    signal_marker = migration_block_time + SIGNAL_MARKER_SECONDS
    fee_fields = {
        "lp_fee_basis_points_raw": 20,
        "coin_creator_fee_basis_points_raw": 5,
        "protocol_fee_basis_points_raw": 5,
    }

    def _entry_event(quote_reserves: int) -> dict[str, Any]:
        # So as RESERVAS importam pra precificar a entrada (AMM simulada
        # contra o estado do pool) -- base/quote_amount_raw (o trade
        # HISTORICO que produziu essas reservas) nao sao usados por
        # find_causal_entry, ficam com valor placeholder.
        return {
            "base_amount_raw": 1,
            "quote_amount_raw": 1,
            "pool_base_token_reserves_raw": 10**15,
            "pool_quote_token_reserves_raw": quote_reserves,
            **fee_fields,
        }

    def _path_event(executed_price_sol: float) -> dict[str, Any]:
        # O rastreamento de preco DEPOIS da entrada (barreira/saida) usa o
        # preco EXECUTADO do proprio trade (quote_amount/base_amount),
        # NUNCA as reservas -- base_amount_raw=1 token (1e6, 6 decimais),
        # quote_amount_raw escalado pra dar exatamente executed_price_sol.
        base_amount_raw = 1_000_000
        quote_amount_raw = round(executed_price_sol * 10**9 * base_amount_raw / 10**6)
        return {
            "base_amount_raw": base_amount_raw,
            "quote_amount_raw": quote_amount_raw,
            "pool_base_token_reserves_raw": 10**15,
            "pool_quote_token_reserves_raw": 10**12,
            **fee_fields,
        }

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "eval.db"
        checkpoint_path = Path(tmp) / "checkpoint.json"
        coverage_report_path = Path(tmp) / "coverage_report.json"

        conn = sqlite3.connect(str(db_path))
        ensure_h2_backfill_schema(conn)
        entry_time = signal_marker + ENTRY_LATENCY_SECONDS + 5  # dentro da janela, apos o limiar de entrada
        after_time = entry_time + 100  # estritamente depois da entrada -- e o que a barreira varre
        # Entrada: reservas base=1e15, quote=1e12 (pool ~1000 SOL, trade de
        # 0.15 SOL e so ~0.015% dele -- slippage desprezivel) -> mid price
        # (1e12/1e9)/(1e15/1e6) = 1e-6 SOL/token; preco de EXECUCAO fica um
        # pouco mais alto so pela fee (~1,3%) -> ~1.013e-6. Depois, sinal
        # sobe pra 2.2e-6 (+~117% sobre a execucao de entrada, bem acima
        # da barreira de +50% com folga de aproximacao) e baseline fica
        # perto de 1e-6 (~-1% sobre a entrada, bem dentro de -30%..+50%,
        # fica NONE -- nem UP nem DOWN).
        rows = [
            ("SIGpump", "SIGMIG", migration_block_time, "SIG_ENTRY", entry_time, _entry_event(10**12)),
            ("SIGpump", "SIGMIG", migration_block_time, "SIG_AFTER", after_time, _path_event(2.2e-6)),
            ("BASEpump", "BASEMIG", migration_block_time, "BASE_ENTRY", entry_time, _entry_event(10**12)),
            ("BASEpump", "BASEMIG", migration_block_time, "BASE_AFTER", after_time, _path_event(1.0e-6)),
        ]
        with conn:
            for pool, mig_sig, mig_bt, sig, bt, event in rows:
                event = dict(event, signature=sig, event_key=f"{sig}:0:pumpswap_buy")
                conn.execute(
                    "INSERT INTO sig_fast_h2_backfill_v0 "
                    "(source, fetched_at, pool_mint, migration_signature, migration_block_time, signature, "
                    "block_time, slot, fetch_sequence, event_type, decode_status, raw_json, decoded_json) "
                    "VALUES ('test', 0, ?, ?, ?, ?, ?, 0, 0, 'pumpswap_buy', 'decoded', '{}', ?)",
                    (pool, mig_sig, mig_bt, sig, bt, json.dumps(event)),
                )
        conn.close()

        checkpoint_path.write_text(
            json.dumps(
                {
                    "stage1": {
                        "SIGpump": {"migration_block_time": migration_block_time, "survived_20min_system_count": True},
                        "BASEpump": {"migration_block_time": migration_block_time, "survived_20min_system_count": False},
                    }
                }
            ),
            encoding="utf-8",
        )
        coverage_report_path.write_text(
            json.dumps(
                {
                    "baseline_pools": ["BASEpump"],
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-02",
                    "stopping_rule": {"train_cutoff_epoch": migration_block_time + 999_999},
                }
            ),
            encoding="utf-8",
        )

        result = run_discovery_evaluation(
            db_path=db_path, checkpoint_path=checkpoint_path, coverage_report_path=coverage_report_path
        )

    assert result.n_signal_train == 1, result
    assert result.n_baseline_train == 1, result
    # tudo caiu no treino (train_cutoff bem depois de ambos os signal_time) --
    # retentor fica vazio, o que faz os dois criterios (a)/(b) do retentor
    # reprovarem por falta de dado (missing != sucesso) -- classification
    # tem que ser FAIL aqui, mas o que importa pro self-check e que o
    # CARREGAMENTO/RESOLUCAO DE PRECO funcionou (edge e EV do TREINO corretos).
    assert result.n_signal_holdout == 0 and result.n_baseline_holdout == 0, result
    assert result.train_edge_pp == 100.0, result  # sinal bateu UP (1/1=100%), baseline nao bateu nada (0/1=0%)
    assert result.classification == CLASSIFICATION_FAIL, result  # retentor vazio nunca pode virar CANDIDATE


def _self_check() -> None:
    _self_check_fee_resolution_missingness()
    _self_check_aggregation()
    _self_check_token_pipeline_and_db_wiring()
    print(
        "self-check OK: resolucao de fee isolada (causal, fallback, missing explicito) + "
        "agregacao (barrier rate + EV/PF + selecao de saida + CANDIDATE/FAIL, "
        "cenario calculavel a mao) + pipeline completo de arquivo (banco real + checkpoint + "
        "coverage_report -> preco/fee/barreira/saida corretos)"
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return 0
    print("Modulo de avaliacao -- sem entrypoint de producao proprio (ver runbook da Fase 4/6).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
