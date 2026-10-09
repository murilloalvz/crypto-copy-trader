"""SIG-FAST H2 Passo B -- sela o bloco de DISCOVERY (2026-08-20 a
2026-09-17, K=26 janelas iniciais, addendum Fase E parte 5 + regra de
parada por contagem da Fase 2 do mandato autonomo). So este bloco: nunca
importa nem abre o arquivo/banco da confirmacao (h2_seal_confirmation_v0.py
e um arquivo separado, sem import nenhum entre os dois). So cobertura --
nunca retorno/MFE/barreira/EV. Nunca imprime URL de RPC.

K_WINDOWS e so o PONTO DE PARTIDA -- se o treino (primeiros 70% do
calendario) ficar com menos de 30 sobreviventes, o proprio
seal_discovery_block_with_stopping_rule estende k automaticamente (mesma
sequencia estavel de janelas, nunca reprocessa o que ja foi selado) ate
atingir >=36 sobreviventes no treino ou esgotar o teto de extensoes -- ver
report["stopping_rule"] no coverage_report.json produzido.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.sig_fast_v0.h2_block_seal_v0 import _self_check, seal_discovery_block_with_stopping_rule
from benchmarks.sig_fast_v0.h2_pilot_v0 import (
    DEFAULT_MAX_CONSECUTIVE_FAILURES,
    DEFAULT_MAX_RPS,
    DISCOVERY_BLOCK_END,
    DISCOVERY_BLOCK_START,
    HELIUS_MAX_RPS_DEFAULT,
    MAX_429_STALL_SECONDS,
    PILOT_SEED,
    PILOT_WINDOW_MINUTES_DEFAULT,
    RpcUsageTracker,
    _load_rpc_url,
    install_rate_limited_rpc,
    load_rotation_rpc_urls,
)
from benchmarks.sig_fast_v0.h2_historical_backfill_v0 import EndpointRotator

BLOCK_NAME = "discovery"
# Addendum Fase E parte 5: K fixado a partir do resultado real do piloto
# (sobreviventes/janela medido), >=30 sobreviventes no treino (70% do
# bloco) com folga de 20%.
K_WINDOWS = 26
DB_PATH = Path("artifacts/sig_fast_h2_discovery_v0/discovery.db")
CHECKPOINT_PATH = Path("artifacts/sig_fast_h2_discovery_v0/checkpoint.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--max-rps", type=float, default=DEFAULT_MAX_RPS)
    parser.add_argument("--helius-max-rps", type=float, default=HELIUS_MAX_RPS_DEFAULT)
    parser.add_argument("--plan-rps", type=float, default=None)
    parser.add_argument("--max-consecutive-failures", type=int, default=DEFAULT_MAX_CONSECUTIVE_FAILURES)
    parser.add_argument("--max-429-stall-seconds", type=float, default=MAX_429_STALL_SECONDS)
    parser.add_argument("--out", type=Path, default=Path("artifacts/sig_fast_h2_discovery_v0/coverage_report.json"))
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    max_rps = args.max_rps
    if args.plan_rps is not None:
        max_rps = min(max_rps, args.plan_rps * 0.5)
    print(
        f"[selagem {BLOCK_NAME}] rate limit efetivo: nao-Helius={max_rps:.2f} req/s, "
        f"Helius={args.helius_max_rps:.2f} req/s"
    )

    rpc_url = _load_rpc_url()
    tracker = RpcUsageTracker()
    restore_rpc = install_rate_limited_rpc(
        max_rps=max_rps,
        helius_url=rpc_url,
        helius_max_rps=args.helius_max_rps,
        max_consecutive_failures=args.max_consecutive_failures,
        tracker=tracker,
        max_429_stall_seconds=args.max_429_stall_seconds,
    )
    rotator = EndpointRotator(load_rotation_rpc_urls())

    from benchmarks.integrated_market_signal_plane_v1.live_shadow import JsonLineProcess, _carbon_command

    carbon = JsonLineProcess(_carbon_command(args.cargo), ready_type="carbon_stream_decoder_ready")
    carbon.start()
    try:
        report = seal_discovery_block_with_stopping_rule(
            block_name=BLOCK_NAME,
            start_date=DISCOVERY_BLOCK_START,
            end_date=DISCOVERY_BLOCK_END,
            initial_k_windows=K_WINDOWS,
            window_minutes=PILOT_WINDOW_MINUTES_DEFAULT,
            seed=PILOT_SEED,
            db_path=DB_PATH,
            checkpoint_path=CHECKPOINT_PATH,
            rpc_url=rpc_url,
            rotator=rotator,
            tracker=tracker,
            carbon=carbon,
        )
    finally:
        carbon.close()
        restore_rpc()

    text = json.dumps(report, indent=2, sort_keys=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
