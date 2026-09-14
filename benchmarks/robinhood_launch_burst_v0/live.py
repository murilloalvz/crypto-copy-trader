"""Prospective feature-only Robinhood/Pons Launch Burst V0 collector."""
from __future__ import annotations
import argparse,json,os,time,urllib.error,urllib.request,uuid
from pathlib import Path
from dotenv import load_dotenv
from src.robinhood_pons_launch_burst_v0 import CURVE_BUY_SIGNATURE,CURVE_SELL_SIGNATURE,METHOD_VERSION,PONS_V2_FACTORY,ROBINHOOD_CHAIN_ID,TOKEN_LAUNCHED_SIGNATURE,WINDOWS_SECONDS,RobinhoodPonsBurstBookV0,decode_curve_trade_log_v0,decode_token_launched_log_v0
DEFAULT_PUBLIC_RPC="https://rpc.mainnet.chain.robinhood.com"
class JsonRpcError(RuntimeError):pass
class RpcClient:
    def __init__(self,url,timeout_s=10.0):self.url=url;self.timeout_s=timeout_s;self._id=0
    def call(self,method,params):
        self._id+=1; payload=json.dumps({"jsonrpc":"2.0","id":self._id,"method":method,"params":params}).encode(); req=urllib.request.Request(self.url,data=payload,headers={"content-type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=self.timeout_s) as r:body=json.loads(r.read().decode())
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as e:raise JsonRpcError(f"{method} transport failure: {e}") from e
        if body.get("error") is not None:raise JsonRpcError(f"{method} rpc error: {body['error']}")
        return body.get("result")
    def chain_id(self):return int(str(self.call("eth_chainId",[])),16)
    def block_number(self):return int(str(self.call("eth_blockNumber",[])),16)
    def block_timestamp(self,n):
        row=self.call("eth_getBlockByNumber",[hex(n),False]);
        if not isinstance(row,dict) or row.get("timestamp") is None:raise JsonRpcError(f"missing block timestamp for {n}")
        return int(str(row["timestamp"]),16)
    def sha3_text(self,text):
        x=self.call("web3_sha3",["0x"+text.encode().hex()]);
        if not isinstance(x,str) or not x.startswith("0x"):raise JsonRpcError("invalid web3_sha3 response")
        return x.lower()
    def get_logs(self,from_block,to_block,addresses):
        if from_block>to_block:return []
        q={"fromBlock":hex(from_block),"toBlock":hex(to_block),"address":addresses}; rows=self.call("eth_getLogs",[q])
        if not isinstance(rows,list):raise JsonRpcError("eth_getLogs did not return a list")
        return [r for r in rows if isinstance(r,dict)]
def _write(path,row):
    with path.open("a",encoding="utf-8") as f:f.write(json.dumps(row,separators=(",",":"))+"\n")
def _p(v,q):
    if not v:return None
    v=sorted(v)
    if len(v)==1:return v[0]
    p=(len(v)-1)*q;l=int(p);h=min(l+1,len(v)-1);f=p-l;return v[l]*(1-f)+v[h]*f
def _summary(v):return {"n":len(v),"p50":_p(v,.5),"p95":_p(v,.95),"p99":_p(v,.99),"max":max(v) if v else None}
def _features(snaps):
    out={}
    for h in WINDOWS_SECONDS:
        c=[r for r in snaps if r["native_eth_cohort"] and r["horizon_seconds"]==h]
        out[str(h)]={"n":len(c),"nonempty":sum(r["trade_count"]>0 for r in c),"trade_count":_summary([float(r["trade_count"]) for r in c]),"signed_quote_flow_over_activity":_summary([r["signed_quote_flow_over_activity"] for r in c if r["signed_quote_flow_over_activity"] is not None]),"buy_fee_share_bps_observed":_summary([r["buy_fee_share_bps_observed"] for r in c if r["buy_fee_share_bps_observed"] is not None]),"deployer_buy_quote_share":_summary([r["deployer_buy_quote_share"] for r in c if r["deployer_buy_quote_share"] is not None]),"top1_buyer_quote_share":_summary([r["top1_buyer_quote_share"] for r in c if r["top1_buyer_quote_share"] is not None]),"snapshot_dispatch_lag_ms":_summary([r["snapshot_dispatch_lag_ms"] for r in c])}
    return out
def run(args):
    load_dotenv(); rpc_url=args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_PUBLIC_RPC; rid=f"robinhood_launch_burst_v0-{int(time.time())}-{uuid.uuid4().hex[:10]}"; run_dir=Path(args.artifacts_root)/rid;run_dir.mkdir(parents=True,exist_ok=False)
    ep=run_dir/"events.jsonl";sp=run_dir/"snapshots.jsonl";rp=run_dir/"report.json";client=RpcClient(rpc_url,args.rpc_timeout_seconds);errors=[];book=RobinhoodPonsBurstBookV0();snaps=[];cache={};poll_lag=[];start=time.time_ns();stop="unknown";initial=final=None;polls=0
    try:
        chain_id=client.chain_id()
        if chain_id!=ROBINHOOD_CHAIN_ID:raise RuntimeError(f"wrong chain id: {chain_id}")
        topics={"token_launched":client.sha3_text(TOKEN_LAUNCHED_SIGNATURE),"curve_buy":client.sha3_text(CURVE_BUY_SIGNATURE),"curve_sell":client.sha3_text(CURVE_SELL_SIGNATURE)}
        latest=client.block_number();initial=latest;next_block=latest+1
        while True:
            if (time.time_ns()-start)/1e9>=args.duration_seconds:stop="duration_elapsed";break
            t=time.perf_counter_ns()
            try:
                latest=client.block_number();polls+=1
                if latest>=next_block:
                    fb=next_block;tb=min(latest,next_block+args.max_block_span-1);flogs=client.get_logs(fb,tb,PONS_V2_FACTORY);new=[]
                    for raw in flogs:
                        bn=int(str(raw.get("blockNumber","0x0")),16);cache.setdefault(bn,client.block_timestamp(bn));raw["observed_at_ns"]=time.time_ns();raw["block_timestamp_s"]=cache[bn];launch=decode_token_launched_log_v0(raw,topic0=topics["token_launched"])
                        if launch and book.add_launch(launch):new.append(launch.curve);_write(ep,{"kind":"launch",**launch.__dict__})
                    wall=time.time_ns();active=[c for c,l in book.launches_by_curve.items() if wall<=l.observed_at_ns+35_000_000_000]
                    for c in new:
                        if c not in active:active.append(c)
                    if active:
                        for raw in client.get_logs(fb,tb,active):
                            bn=int(str(raw.get("blockNumber","0x0")),16);cache.setdefault(bn,client.block_timestamp(bn));raw["observed_at_ns"]=time.time_ns();raw["block_timestamp_s"]=cache[bn];trade=decode_curve_trade_log_v0(raw,buy_topic0=topics["curve_buy"],sell_topic0=topics["curve_sell"])
                            if trade and book.add_trade(trade):_write(ep,{"kind":"trade",**trade.__dict__})
                    final=tb;next_block=tb+1
            except Exception as e:
                errors.append(f"{type(e).__name__}:{e}")
                if len(errors)>=args.max_transport_errors:stop="transport_error_limit";break
            for s in book.ready_snapshots(time.time_ns()):row=s.to_dict();snaps.append(row);_write(sp,row)
            poll_lag.append((time.perf_counter_ns()-t)/1e6);time.sleep(args.poll_ms/1000)
        for s in book.ready_snapshots(time.time_ns()):row=s.to_dict();snaps.append(row);_write(sp,row)
        counts=book.counts();gates={"chain_id_correct":chain_id==ROBINHOOD_CHAIN_ID,"transport_errors_zero":len(errors)==0,"feature_only":True,"economic_outcomes_closed":True,"selector_unfrozen":True}
        cls="FAIL_ROBINHOOD_LAUNCH_BURST_TRANSPORT_V0" if stop=="transport_error_limit" else ("PASS_ROBINHOOD_LAUNCH_BURST_CAPTURE_V0_NO_NATIVE_LAUNCHES" if counts["native_eth_launches"]==0 else "PASS_ROBINHOOD_LAUNCH_BURST_FEATURE_CAPTURE_V0")
        report={"type":"robinhood_pons_launch_burst_live_report_v0","method_version":METHOD_VERSION,"classification":cls,"feature_only":True,"economic_outcomes_opened":False,"selector_frozen":False,"chain_id":chain_id,"factory":PONS_V2_FACTORY,"rpc_kind":"json_rpc_polling_v0","public_rpc_default_used":rpc_url==DEFAULT_PUBLIC_RPC,"start_wall_ns":start,"finished_wall_ns":time.time_ns(),"duration_seconds_requested":args.duration_seconds,"stop_reason":stop,"initial_block":initial,"final_block":final,"polls":polls,"poll_ms":args.poll_ms,"poll_latency_ms":_summary(poll_lag),"counts":counts,"feature_report_native_eth":_features(snaps),"topic0":topics,"transport_errors":errors,"gates":gates,"notes":["feature_only_no_selector_no_outcomes","native_eth_launches_are_headline_cohort","custom_pair_launches_preserved_as_coverage_only","availability_clock_is_local_observed_at_ns","json_rpc_polling_is_bootstrap_acquisition_not_final_sequencer_feed"]}
    except Exception as e:report={"type":"robinhood_pons_launch_burst_live_report_v0","method_version":METHOD_VERSION,"classification":"FAIL_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0","feature_only":True,"economic_outcomes_opened":False,"selector_frozen":False,"error":f"{type(e).__name__}:{e}","transport_errors":errors}
    rp.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2));return report
def main():
    p=argparse.ArgumentParser();p.add_argument("--duration-seconds",type=int,default=900);p.add_argument("--poll-ms",type=int,default=350);p.add_argument("--max-block-span",type=int,default=20);p.add_argument("--max-transport-errors",type=int,default=5);p.add_argument("--rpc-timeout-seconds",type=float,default=10);p.add_argument("--rpc-url");p.add_argument("--artifacts-root",default="artifacts/robinhood_launch_burst_v0");a=p.parse_args();run(a)
if __name__=="__main__":main()
