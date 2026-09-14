"""Compact report summarizer for Robinhood Launch Burst V0."""
from __future__ import annotations
import argparse,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument("--root",default="artifacts/robinhood_launch_burst_v0");a=p.parse_args();root=Path(a.root);runs=sorted((d for d in root.iterdir() if d.is_dir()),key=lambda d:d.stat().st_mtime,reverse=True)
    if not runs:raise SystemExit("no Robinhood Launch Burst V0 runs found")
    run=runs[0];r=json.loads((run/"report.json").read_text(encoding="utf-8"));out={"run":run.name,"classification":r.get("classification"),"stop_reason":r.get("stop_reason"),"chain_id":r.get("chain_id"),"factory":r.get("factory"),"counts":r.get("counts"),"poll_latency_ms":r.get("poll_latency_ms"),"feature_report_native_eth":r.get("feature_report_native_eth"),"transport_errors":r.get("transport_errors"),"gates":r.get("gates"),"economic_outcomes_opened":r.get("economic_outcomes_opened"),"selector_frozen":r.get("selector_frozen")};print(json.dumps(out,indent=2))
if __name__=="__main__":main()
