from __future__ import annotations

from pathlib import Path

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_control_taker_sim_v0.run_helius_holders import (
    _discover_control_via_helius_holders,
)
from benchmarks.launch_burst_control_taker_sim_v0.smart_ladder_25 import (
    run_smart_ladder_25,
)

CORRECTED_POLICY = Path(__file__).with_name("smart_ladder_25_policy_v0.frozen.json")


def main() -> int:
    original_discover = sim._discover_control
    original_runner = sim.run_smart_exit
    original_policy = sim.DEFAULT_POLICY
    sim._discover_control = _discover_control_via_helius_holders
    sim.run_smart_exit = run_smart_ladder_25
    sim.DEFAULT_POLICY = CORRECTED_POLICY
    try:
        return sim.main()
    finally:
        sim._discover_control = original_discover
        sim.run_smart_exit = original_runner
        sim.DEFAULT_POLICY = original_policy


if __name__ == "__main__":
    raise SystemExit(main())
