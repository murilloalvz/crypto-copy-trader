import json,tempfile,unittest
from pathlib import Path
from benchmarks.robinhood_launch_burst_v0.offline import run as offline_run
from src.robinhood_pons_launch_burst_v0 import PonsLaunchObservationV0,PonsTradeObservationV0,RobinhoodPonsBurstBookV0,ZERO_ADDRESS,build_snapshot_v0,decode_curve_trade_log_v0,decode_token_launched_log_v0

def topic_address(a):return "0x"+a[2:].lower().rjust(64,"0")
def word(v):return f"{v:064x}"
def data_address(a):return word(int(a,16))
class RobinhoodPonsLaunchBurstV0Tests(unittest.TestCase):
 def setUp(self):
  self.token="0x"+"11"*20;self.curve="0x"+"22"*20;self.deployer="0x"+"33"*20;self.buyer="0x"+"44"*20;self.buyer2="0x"+"55"*20;self.recipient="0x"+"66"*20
  self.launch=PonsLaunchObservationV0(self.token,self.curve,self.deployer,ZERO_ADDRESS,0,4_200_000_000_000_000_000,100,0,1,"0xlaunch","0xblock100",1_000_000_000,1000)
 def trade(self,side,actor,quote,token,fee,tax,delay_ms,idx):return PonsTradeObservationV0(side,self.curve,actor,actor,quote,token,fee,tax,100+idx,0,idx,f"0xtx{idx}",f"0xblock{100+idx}",self.launch.observed_at_ns+delay_ms*1_000_000,1000+idx)
 def test_token_launched_decoder(self):
  t="0x"+"aa"*32;raw={"topics":[t,topic_address(self.token),topic_address(self.curve),topic_address(self.deployer)],"data":"0x"+data_address(ZERO_ADDRESS)+word(7)+word(42),"blockNumber":hex(123),"transactionIndex":hex(2),"logIndex":hex(9),"transactionHash":"0xabc","blockHash":"0xdef","observed_at_ns":99,"block_timestamp_s":1234};r=decode_token_launched_log_v0(raw,topic0=t);self.assertEqual(r.curve,self.curve);self.assertTrue(r.is_native_eth_quote);self.assertEqual(r.launch_config_id,7)
 def test_curve_buy_sell_decode(self):
  b="0x"+"bb"*32;s="0x"+"cc"*32;base={"address":self.curve,"blockNumber":hex(101),"transactionIndex":hex(0),"transactionHash":"0xtrade","blockHash":"0xblock","observed_at_ns":2_000_000_000};buy=dict(base,topics=[b,topic_address(self.buyer),topic_address(self.recipient)],data="0x"+word(1000)+word(5000)+word(100)+word(20),logIndex=hex(1));sell=dict(base,topics=[s,topic_address(self.buyer),topic_address(self.recipient)],data="0x"+word(5000)+word(900)+word(90)+word(10),logIndex=hex(2));br=decode_curve_trade_log_v0(buy,buy_topic0=b,sell_topic0=s);sr=decode_curve_trade_log_v0(sell,buy_topic0=b,sell_topic0=s);self.assertEqual((br.side,br.quote_amount_raw,br.token_amount_raw),("BUY",1000,5000));self.assertEqual((sr.side,sr.quote_amount_raw,sr.token_amount_raw),("SELL",900,5000))
 def test_snapshot_causal_future_excluded(self):
  rows=[self.trade("BUY",self.buyer,1000,10000,250,20,200,2),self.trade("BUY",self.buyer2,500,4000,20,10,800,3),self.trade("SELL",self.buyer,300,2000,10,5,900,4),self.trade("BUY",self.buyer,9999,1,1,1,1200,5)];x=build_snapshot_v0(launch=self.launch,trades=rows,horizon_seconds=1,snapshot_observed_at_ns=2_100_000_000);self.assertEqual(x.trade_count,3);self.assertEqual(x.signed_quote_flow_raw,1200);self.assertEqual(x.time_to_3_trades_ms,900);self.assertIsNone(x.time_to_5_trades_ms)
 def test_deployer_and_concentration(self):
  rows=[self.trade("BUY",self.deployer,700,1000,100,0,100,2),self.trade("BUY",self.buyer,200,200,10,0,200,3),self.trade("BUY",self.buyer2,100,90,5,0,300,4)];x=build_snapshot_v0(launch=self.launch,trades=rows,horizon_seconds=1,snapshot_observed_at_ns=2_000_000_000);self.assertAlmostEqual(x.deployer_buy_quote_share,.7);self.assertAlmostEqual(x.top1_buyer_quote_share,.7);self.assertAlmostEqual(x.top3_buyer_quote_share,1)
 def test_custom_pair_separate(self):
  b=RobinhoodPonsBurstBookV0();self.assertTrue(b.add_launch(self.launch));self.assertFalse(b.add_launch(self.launch));c=PonsLaunchObservationV0("0x"+"77"*20,"0x"+"88"*20,self.deployer,"0x"+"99"*20,1,123,101,0,1,"0xcustom","0xblock101",2_000_000_000);b.add_launch(c);self.assertEqual(b.counts()["native_eth_launches"],1);self.assertEqual(b.counts()["custom_pair_launches"],1)
 def test_offline_feature_only(self):
  tr=self.trade("BUY",self.buyer,1000,5000,200,10,100,2);payload={"type":"robinhood_pons_launch_burst_input_v0","observations":[{"kind":"launch",**self.launch.__dict__},{"kind":"trade",**tr.__dict__}]}
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/"i.json";p.write_text(json.dumps(payload));r=offline_run(p)
  self.assertTrue(r["feature_only"]);self.assertFalse(r["economic_outcomes_opened"]);self.assertFalse(r["selector_frozen"]);self.assertEqual(set(r["feature_report_native_eth"]),{"1","5","10","30"})
if __name__=="__main__":unittest.main()
