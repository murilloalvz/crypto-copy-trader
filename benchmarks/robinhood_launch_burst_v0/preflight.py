"""Network preflight for Robinhood/Pons Launch Burst V0."""
from __future__ import annotations
import argparse,json,os
from dotenv import load_dotenv
from benchmarks.robinhood_launch_burst_v0.live import DEFAULT_PUBLIC_RPC,RpcClient
from src.robinhood_pons_launch_burst_v0 import CURVE_BUY_SIGNATURE,CURVE_SELL_SIGNATURE,PONS_V2_FACTORY,ROBINHOOD_CHAIN_ID,TOKEN_LAUNCHED_SIGNATURE

def main():
    load_dotenv();p=argparse.ArgumentParser();p.add_argument("--rpc-url");a=p.parse_args();url=a.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_PUBLIC_RPC;c=RpcClient(url,10)
    try:
        chain=c.chain_id();latest=c.block_number();topics={"TokenLaunched":c.sha3_text(TOKEN_LAUNCHED_SIGNATURE),"CurveBuy":c.sha3_text(CURVE_BUY_SIGNATURE),"CurveSell":c.sha3_text(CURVE_SELL_SIGNATURE)}
        result={"classification":"PASS_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0" if chain==ROBINHOOD_CHAIN_ID else "FAIL_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0","chain_id":chain,"expected_chain_id":ROBINHOOD_CHAIN_ID,"latest_block":latest,"factory":PONS_V2_FACTORY,"public_rpc_default_used":url==DEFAULT_PUBLIC_RPC,"topic0":topics,"economic_outcomes_opened":False}
    except Exception as e:result={"classification":"FAIL_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0","error":f"{type(e).__name__}:{e}","economic_outcomes_opened":False}
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
