"""Offline feature-only evaluator for Robinhood/Pons Launch Burst V0."""
from __future__ import annotations
import argparse, json
from collections import defaultdict
from pathlib import Path
from src.robinhood_pons_launch_burst_v0 import METHOD_VERSION, WINDOWS_SECONDS, PonsLaunchObservationV0, PonsTradeObservationV0, RobinhoodPonsBurstBookV0

def _p(values,q):
    if not values:return None
    values=sorted(values)
    if len(values)==1:return values[0]
    pos=(len(values)-1)*q; lo=int(pos); hi=min(lo+1,len(values)-1); f=pos-lo
    return values[lo]*(1-f)+values[hi]*f

def _summary(values):
    return {"n":len(values),"p50":_p(values,.5),"p75":_p(values,.75),"p90":_p(values,.9),"p95":_p(values,.95),"p99":_p(values,.99),"min":min(values) if values else None,"max":max(values) if values else None,"mean":sum(values)/len(values) if values else None}

def load_normalized_input(path:Path):
    payload=json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type")!="robinhood_pons_launch_burst_input_v0":raise ValueError("unexpected input type")
    obs=payload.get("observations")
    if not isinstance(obs,list):raise ValueError("observations must be a list")
    out=[]
    for row in obs:
        kind=row.get("kind"); data={k:v for k,v in row.items() if k!="kind"}
        if kind=="launch":out.append(PonsLaunchObservationV0(**data))
        elif kind=="trade":out.append(PonsTradeObservationV0(**data))
        else:raise ValueError(f"unsupported observation kind: {kind!r}")
    return out

def run(path:Path)->dict:
    rows=load_normalized_input(path); book=RobinhoodPonsBurstBookV0(); max_ns=0
    for row in rows:
        max_ns=max(max_ns,row.observed_at_ns)
        book.add_launch(row) if isinstance(row,PonsLaunchObservationV0) else book.add_trade(row)
    snapshots=book.ready_snapshots(max_ns+max(WINDOWS_SECONDS)*1_000_000_000+1)
    by=defaultdict(list)
    for row in snapshots:
        if row.native_eth_cohort:by[row.horizon_seconds].append(row)
    feature={}
    for h in WINDOWS_SECONDS:
        c=by[h]
        feature[str(h)]={"n":len(c),"nonempty":sum(r.trade_count>0 for r in c),"trade_count":_summary([float(r.trade_count) for r in c]),"signed_quote_flow_over_activity":_summary([r.signed_quote_flow_over_activity for r in c if r.signed_quote_flow_over_activity is not None]),"buy_fee_share_bps_observed":_summary([r.buy_fee_share_bps_observed for r in c if r.buy_fee_share_bps_observed is not None]),"deployer_buy_quote_share":_summary([r.deployer_buy_quote_share for r in c if r.deployer_buy_quote_share is not None]),"top1_buyer_quote_share":_summary([r.top1_buyer_quote_share for r in c if r.top1_buyer_quote_share is not None]),"first_trade_delay_ms":_summary([r.first_trade_delay_ms for r in c if r.first_trade_delay_ms is not None]),"time_to_5_trades_ms":_summary([r.time_to_5_trades_ms for r in c if r.time_to_5_trades_ms is not None]),"snapshot_dispatch_lag_ms":_summary([r.snapshot_dispatch_lag_ms for r in c])}
    return {"type":"robinhood_pons_launch_burst_feature_report_v0","method_version":METHOD_VERSION,"feature_only":True,"economic_outcomes_opened":False,"selector_frozen":False,"counts":book.counts(),"feature_report_native_eth":feature,"snapshots":[r.to_dict() for r in snapshots]}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--output",required=True); a=p.parse_args(); result=run(Path(a.input)); Path(a.output).write_text(json.dumps(result,indent=2),encoding="utf-8"); print(json.dumps({k:v for k,v in result.items() if k!="snapshots"},indent=2))
if __name__=="__main__":main()
