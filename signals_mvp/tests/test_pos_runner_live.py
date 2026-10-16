"""POS-RUNNER-V0 ao vivo (Parte B), sem rede: descoberta (lista REAL do GT), linhagem (transacoes REAIS de migracao),
candles congelados, alertas, paper A/B, CSV, reinicio, orcamento e integracao com o engine."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional

from ..config import ConfigError, build_config, make_paths
from ..http import ApiError, CallBudget, RateLimited
from ..models import ChainCtx
from ..pos_runner import charts
from ..pos_runner.candles import Bar, tf_seconds
from ..pos_runner.live import (
    LAG_S,
    VERIFY_MAX_ATTEMPTS,
    Lineage,
    LineageVerifier,
    LiveSettings,
    PosRunnerLive,
    verify_lineage,
)
from ..pos_runner.solana_rpc import RpcError
from ..storage import POS_RUNNER_COLUMNS, Storage
from ..util import iso_utc, parse_iso
from .fakes import FakeClock, FakeTelegram, load_fixture
from .helpers import Env, read_csv, shipped_config
from .test_pos_runner import GRAD, H, params, textbook

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL = "So11111111111111111111111111111111111111112"
SUPPLY = 1e9
CTX = ChainCtx("solana", "solana", "solana", frozenset({SOL, USDC}), frozenset({"meteora-dbc"}))
LINKS = {"axiom": "https://axiom.trade/meme/{pool}", "gmgn": "https://gmgn.ai/{gmgn_slug}/token/{token}",
         "dexscreener": "https://dexscreener.com/{dexscreener_slug}/{pool}"}
TF_OF = {("minute", 5): "5m", ("hour", 1): "1h", ("hour", 4): "4h"}


def pools_json(items: list[dict]) -> dict:
    """Resposta no formato de `networks/solana/.../pools` do GeckoTerminal (so os campos que o parser le)."""
    data, included = [], {
        USDC: {"id": f"solana_{USDC}", "type": "token", "attributes": {"address": USDC, "symbol": "USDC", "name": "USD Coin"}},
        SOL: {"id": f"solana_{SOL}", "type": "token", "attributes": {"address": SOL, "symbol": "SOL", "name": "Wrapped SOL"}},
    }
    for it in items:
        quote = it.get("quote", USDC)
        data.append({
            "id": f"solana_{it['pool']}", "type": "pool",
            "attributes": {"address": it["pool"], "name": f"{it['symbol']} / x", "pool_created_at": iso_utc(it["created"]),
                           "fdv_usd": str(it["mc"]), "market_cap_usd": None, "reserve_in_usd": "100000"},
            "relationships": {"base_token": {"data": {"id": f"solana_{it['mint']}", "type": "token"}},
                              "quote_token": {"data": {"id": f"solana_{quote}", "type": "token"}},
                              "dex": {"data": {"id": it.get("dex", "pumpswap"), "type": "dex"}}},
        })
        included[it["mint"]] = {"id": f"solana_{it['mint']}", "type": "token",
                                "attributes": {"address": it["mint"], "symbol": it["symbol"], "name": it["symbol"]}}
    return {"data": data, "included": list(included.values())}


class World:
    """GeckoTerminal de mentira: listas de pools e OHLCV (em USDC por token) que so existem ate o relogio. O candle em
    andamento volta com valores PARCIAIS diferentes do final: se algum dia for consumido, os candles congelados divergem."""

    class _Limiter:
        @staticmethod
        def blocked_for() -> float:
            return 0.0

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.headers: dict[str, str] = {}
        self.limiter = self._Limiter()
        self.series: dict[tuple[str, str], list[Bar]] = {}
        self.lists: dict[str, dict] = {}
        self.calls: list[str] = []
        self.fail: Optional[Exception] = None

    def add_series(self, pool: str, tf: str, mc_bars: list[Bar]) -> None:
        self.series[(pool, tf)] = [Bar(b.ts, b.open / SUPPLY, b.high / SUPPLY, b.low / SUPPLY, b.close / SUPPLY, b.volume) for b in mc_bars]

    def get_json(self, path: str, params: Any = None, max_wait_s: float = 5.0) -> Any:
        self.calls.append(path)
        if self.fail is not None:
            exc, self.fail = self.fail, None
            raise exc
        if "/ohlcv/" in path:
            pool = path.split("/pools/")[1].split("/")[0]
            tf = TF_OF[(path.rsplit("/", 1)[1], int(params["aggregate"]))]
            step, now, before = tf_seconds(tf), self.clock(), int(params["before_timestamp"])
            rows = []
            for b in self.series.get((pool, tf), []):
                if b.ts > before or b.ts > now:
                    continue
                if b.ts + step > now:
                    b = Bar(b.ts, b.open, b.open * 3, b.open * 0.3, b.open * 2, 99_999.0)
                rows.append([b.ts, b.open, b.high, b.low, b.close, b.volume])
            rows = rows[-int(params["limit"]):]
            return {"data": {"attributes": {"ohlcv_list": list(reversed(rows))}}}
        return self.lists.get(path, {"data": [], "included": []})


def ok_lineage(grad_ts: float = GRAD + 60, launchpad: str = "pumpfun"):
    return lambda rpc, pool, mint, created, lp: Lineage("ok", "", launchpad, grad_ts, USDC, SUPPLY, "SIG", "MigrateV2")


class LiveHarness:
    def __init__(self, settings: Optional[LiveSettings] = None, start: float = GRAD + 8 * H + 120, telegram: bool = True):
        self.tmp = Path(tempfile.mkdtemp(prefix="pr_live_"))
        self.paths = make_paths(self.tmp)
        self.storage = Storage(self.paths)
        self.clock = FakeClock(start)
        self.world = World(self.clock)
        self.tg = FakeTelegram() if telegram else None
        self.settings = settings or LiveSettings(ligado=True, timeframes=("1h",), max_pools=5, chamadas_por_ciclo=3,
                                                 descoberta_min=3, fontes=("pumpswap",), grafico=False)
        self.params = params()
        self.live = self.new_live()
        self.verifier = LineageVerifier(self.storage, None, clock=self.clock, verify=ok_lineage())

    def new_live(self, telegram: Any = None) -> PosRunnerLive:
        return PosRunnerLive(self.settings, self.params, self.storage, self.world, CTX, telegram or self.tg, LINKS, "solana",
                             self.paths.dados / "pos_runner", clock=self.clock)

    def list_pool(self, pool: str = "POOL1", mint: str = "MINT1", symbol: str = "CAT", mc: float = 1_000_000.0,
                  created: float = GRAD + 60, dex: str = "pumpswap") -> None:
        self.world.lists["networks/solana/dexes/pumpswap/pools"] = pools_json(
            [{"pool": pool, "mint": mint, "symbol": symbol, "mc": mc, "created": created, "dex": dex}])

    def tick(self, budget: int = 10, keep: int = 1, live: Optional[PosRunnerLive] = None) -> dict:
        return (live or self.live).tick(self.clock(), CallBudget(budget), keep)

    def run_hours(self, hours: int, live: Optional[PosRunnerLive] = None) -> None:
        for _ in range(hours):
            self.clock.advance(H)
            self.tick(live=live)

    def texts(self) -> list[str]:
        assert self.tg is not None
        return [t for t, _ in self.tg.sent] + [c for _, c, _, _ in self.tg.photos]

    def close(self) -> None:
        self.storage.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def start_tracking(h: LiveHarness) -> None:
    h.world.add_series("POOL1", "1h", textbook().bars)
    h.list_pool()
    h.tick()                       # descoberta -> pendente
    h.verifier.step()              # linhagem -> verificado
    h.tick()                       # vaga -> ativo + carga inicial do 1h


class DiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_real_trending_list_keeps_only_young_graduation_pools_above_the_runner_floor(self) -> None:
        from ..geckoterminal import parse_pools_response
        now = parse_iso("2026-10-15T23:44:00Z")          # hora da captura da resposta real
        snaps = parse_pools_response(load_fixture("gt_trending_solana.json"), CTX, now)
        added = self.h.live.offer(snaps, now, fonte="trending")
        rows = self.h.storage.pr_pools("pendente")
        self.assertEqual(added, len(rows))
        self.assertGreater(len(rows), 3)
        expected = {s.pool for s in snaps if s.dex in ("pumpswap", "raydium", "meteora-damm-v2") and not s.both_reference
                    and 300_000 <= (s.mcap_usd or s.fdv_usd or 0) <= 50_000_000 and now - s.created_ts <= 14 * 86400}
        mints = {}
        for s in snaps:
            if s.pool in expected:
                mints.setdefault(s.token, s.pool)
        self.assertEqual({r["pool"] for r in rows}, set(mints.values()))     # um pool por token
        for r in rows:
            info = json.loads(r["info"])
            self.assertIn(r["dex"], ("pumpswap", "raydium", "meteora-damm-v2"))
            self.assertIsNotNone(info["created_ts"])
            self.assertIn(info["side"], ("base", "quote"))
        self.assertEqual(self.h.live.offer(snaps, now), 0)                  # ja vistos: nao duplica

    def test_disabled_does_nothing(self) -> None:
        self.h.live.settings = LiveSettings(ligado=False)
        self.h.list_pool()
        self.assertEqual(self.h.live.wanted(self.h.clock()), 0)
        self.assertEqual(self.h.tick()["chamadas"], 0)
        self.assertEqual(self.h.world.calls, [])


class LineageTest(unittest.TestCase):
    """Transacoes REAIS de migracao (getTransaction jsonParsed) dos exemplos SOLCAT, ZILLIONS e FLAME, lidas pelo mesmo
    metodo da enumeracao da Parte A (conta-chave do launchpad numa janela em volta da criacao)."""

    CASES = {
        "pumpfun": ("rpc_tx_migrate_pumpfun.json", "9Hr6NXw5WSffxNQnqxwZyhRw81uz3PpB7RF9J3i9nMt1", "9U1f18idDeySFnYrurxqT1f5n5nE4g4Uk5LLzP69bh1"),
        "raydium_launchlab": ("rpc_tx_migrate_launchlab.json", "82BhSZXxSXBKsAmyHJ5NxkCd6JrSUBrmPsxYgu7Byvns", "8gMWXHfSwBRSLc2wKtLv24JYboCAsKaEqfC5cXLeZJXL"),
        "meteora_dbc": ("rpc_tx_migrate_dbc.json", "23B6d3FvDu2eiZxyBLgWdm2W2vn1bdRwJTR6NCfQpxGE", "9oXA1VWKNiYDYa6VKHBFFBBvZdvuhw1b2eD5Aka7YrVt"),
    }

    class Rpc:
        """A conta-chave do launchpad teve, na janela, uma transacao com falha e a migracao (real)."""

        def __init__(self, tx: dict, fail: Optional[Exception] = None):
            self.tx = tx
            self.fail = fail
            self.accounts: list[str] = []

        def signatures(self, address, before=None, until=None, limit=1000):
            if self.fail:
                raise self.fail
            self.accounts.append(address)
            bt = self.tx["blockTime"]
            return [{"signature": "FALHOU", "blockTime": bt + 5, "err": {"x": 1}}, {"signature": "MIGRACAO", "blockTime": bt, "err": None}]

        def call(self, method, params):
            assert method == "getTransaction" and params[0] == "MIGRACAO"
            return self.tx

        def token_supply(self, mint):
            return 975_188_456.39

    @staticmethod
    def enumerate_fn(rpc, spec, start, end):
        from ..pos_runner.enumerate import enumerate_window
        return enumerate_window(rpc, spec, start, end, anchor_fn=lambda r, t: ("ANCORA", 1, t))

    def tx(self, name: str) -> dict:
        return load_fixture(name)["result"]

    def test_the_three_real_migrations_are_accepted(self) -> None:
        from ..pos_runner.enumerate import LAUNCHPADS
        for launchpad, (fixture, pool, mint) in self.CASES.items():
            tx = self.tx(fixture)
            rpc = self.Rpc(tx)
            res = verify_lineage(rpc, pool, mint, tx["blockTime"] + 30, launchpad, enumerate_fn=self.enumerate_fn)
            self.assertEqual(res.status, "ok", (launchpad, res.motivo))
            self.assertEqual(res.launchpad, launchpad)
            self.assertEqual(res.grad_ts, float(tx["blockTime"]))
            self.assertEqual(rpc.accounts, list(LAUNCHPADS[launchpad].accounts))   # so a conta-chave, nunca o pool

    def test_other_pool_other_token_non_migration_and_wrong_launchpad_are_rejected(self) -> None:
        fixture, pool, mint = self.CASES["pumpfun"]
        tx = self.tx(fixture)
        res = verify_lineage(self.Rpc(tx), "OUTROPOOL", mint, tx["blockTime"], "pumpfun", enumerate_fn=self.enumerate_fn)
        self.assertEqual(res.status, "rejeitado")
        self.assertIn("nenhuma migracao pumpfun criou este pool", res.motivo)
        self.assertIn("outro token", verify_lineage(self.Rpc(tx), pool, "OUTROMINT", tx["blockTime"], "pumpfun",
                                                    enumerate_fn=self.enumerate_fn).motivo)
        swap = copy.deepcopy(tx)
        swap["meta"]["logMessages"] = [m.replace("Instruction: MigrateV2", "Instruction: Buy") for m in swap["meta"]["logMessages"]]
        self.assertEqual(verify_lineage(self.Rpc(swap), pool, mint, tx["blockTime"], "pumpfun", enumerate_fn=self.enumerate_fn).status,
                         "rejeitado")
        # pool do PumpSwap conferido como se fosse da DBC: a migracao da DBC nao criou este pool
        self.assertEqual(verify_lineage(self.Rpc(tx), pool, mint, tx["blockTime"], "meteora_dbc", enumerate_fn=self.enumerate_fn).status,
                         "rejeitado")
        self.assertEqual(verify_lineage(self.Rpc(tx), pool, mint, tx["blockTime"], None).status, "rejeitado")

    def test_rpc_failure_is_a_retry_not_a_rejection(self) -> None:
        fixture, pool, mint = self.CASES["pumpfun"]
        tx = self.tx(fixture)
        res = verify_lineage(self.Rpc(tx, fail=RpcError("exhausted", "getSignaturesForAddress: 4 tentativas sem resposta")),
                             pool, mint, tx["blockTime"], "pumpfun", enumerate_fn=self.enumerate_fn)
        self.assertEqual(res.status, "erro")

        def broken(rpc, t):
            raise RpcError("exhausted", "getBlock: 4 tentativas sem resposta")

        from ..pos_runner.enumerate import enumerate_window
        res = verify_lineage(self.Rpc(tx), pool, mint, tx["blockTime"], "pumpfun",
                             enumerate_fn=lambda rpc, spec, a, b: enumerate_window(rpc, spec, a, b, anchor_fn=broken))
        self.assertEqual(res.status, "erro")

    def test_verifier_status_flow_backoff_and_dex_mismatch(self) -> None:
        h = LiveHarness()
        try:
            h.list_pool()
            h.tick()
            outcomes = iter([Lineage("erro", "rpc fora")] * VERIFY_MAX_ATTEMPTS)
            h.verifier.verify = lambda *a: next(outcomes)
            self.assertTrue(h.verifier.step())
            self.assertFalse(h.verifier.step())                 # espera crescente antes de tentar de novo
            for _ in range(VERIFY_MAX_ATTEMPTS - 1):
                h.clock.advance(3600 * 24)
                self.assertTrue(h.verifier.step())
            self.assertEqual(h.storage.pr_pool("POOL1")["status"], "rejeitado")
            h.list_pool(pool="POOL2", mint="MINT2", dex="meteora-damm-v2")
            h.live.next_discovery = 0
            h.tick()
            h.verifier.verify = ok_lineage(launchpad="pumpfun")   # DEX da DBC, linhagem do pump.fun: nao bate
            h.verifier.step()
            row = h.storage.pr_pool("POOL2")
            self.assertEqual(row["status"], "rejeitado")
            self.assertIn("nao e a de graduacao", row["motivo"])
        finally:
            h.close()


class LiveFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.h = LiveHarness()

    def tearDown(self) -> None:
        self.h.close()

    def test_watch_entry_paper_exit_result_and_csv(self) -> None:
        h = self.h
        start_tracking(h)
        row = h.storage.pr_pool("POOL1")
        self.assertEqual(row["status"], "ativo")
        self.assertAlmostEqual(row["l_bc"], textbook().bars[0].open)
        h.run_hours(21)                                      # ate o martelo (caixa armada) fechar
        watch = [t for t in h.texts() if t.startswith("👀")]
        self.assertEqual(len(watch), 1, h.texts())
        self.assertIn("Caixa S", watch[0])
        h.run_hours(3)                                       # rompimento
        entries = [t for t in h.texts() if t.startswith("🟢")]
        self.assertEqual(len(entries), 1, h.texts())
        self.assertIn("ENTRADA POS-RUNNER [1h]", entries[0])
        self.assertIn("Sinal #1 (primário)", entries[0])
        signal = h.storage.pr_signals()[0]
        self.assertEqual(signal["status"], "aberto")
        self.assertIsNotNone(signal["tg_message_id"])
        h.run_hours(50)                                      # lateral: sai pelo stop de tempo (48 candles)
        signal = h.storage.pr_signal(signal["id"])
        self.assertEqual(signal["status"], "fechado")
        self.assertEqual((signal["reason_a"], signal["reason_b"]), ("tempo", "tempo"))
        self.assertLess(signal["result_a"], 0)               # lateral + custos = negativo
        exits = [t for t in h.texts() if t.startswith("🟡")]
        self.assertEqual(len(exits), 1)
        self.assertIn("TEMPO", exits[0])
        self.assertTrue(any(t.startswith("📊") for t in h.texts()))
        self.assertIn(signal["tg_message_id"], h.tg.replies)   # saidas respondem a mensagem da entrada
        h.storage.export_csvs()
        rows = read_csv(h.paths.dados / "pos_runner.csv")
        self.assertEqual(list(rows[0].keys()), POS_RUNNER_COLUMNS)
        r = rows[0]
        self.assertEqual((r["contrato"], r["launchpad"], r["tf"]), ("MINT1", "pumpfun", "1h"))
        self.assertEqual(float(r["entrada_mc"]), 330_000.0)  # open do candle seguinte ao sinal
        self.assertEqual(float(r["tp_mc"]), 950_000.0)        # 95% do pico
        self.assertEqual(r["motivo_saida"], "A=tempo; B=tempo")
        self.assertEqual(r["versao_config"], h.params.version)
        detail = read_csv(h.paths.dados / "pos_runner_detalhe.csv")
        self.assertEqual(detail[0]["status"], "fechado")
        self.assertEqual(detail[0]["alerta_enviado"], "1")

    def test_frozen_bars_are_the_final_candles_never_the_one_in_progress(self) -> None:
        h = self.h
        start_tracking(h)
        h.run_hours(30)
        frozen = h.storage.pr_bars("POOL1", "1h")
        world = {b.ts: b for b in h.world.series[("POOL1", "1h")]}
        self.assertTrue(frozen)
        for ts, o, hi, lo, c, v, filled in frozen:
            b = world[ts]
            self.assertAlmostEqual(c, b.close * SUPPLY)
            self.assertAlmostEqual(hi, b.high * SUPPLY)
            self.assertLessEqual(ts + H, h.clock() - LAG_S)       # so candle fechado (+ folga de indexacao)

    def test_restart_rebuilds_the_same_state_without_repeating_alerts(self) -> None:
        h = self.h
        start_tracking(h)
        h.run_hours(24)
        before = list(h.texts())
        bars = len(h.live.dets[("POOL1", "1h")].bars)
        tg2 = FakeTelegram()
        live2 = h.new_live(tg2)
        h.clock.advance(H)
        h.tick(live=live2)
        self.assertEqual(len(live2.dets[("POOL1", "1h")].bars), bars + 1)
        self.assertEqual([t for t, _ in tg2.sent if t.startswith(("👀", "🟢"))], [])
        self.assertEqual(len(h.storage.pr_signals()), 1)
        self.assertEqual(before, h.texts())

    def test_bot_off_during_the_breakout_records_paper_but_sends_no_stale_alert(self) -> None:
        h = self.h
        start_tracking(h)
        h.run_hours(20)
        h.clock.advance(10 * H)                              # bot desligado 10 h (o rompimento acontece no meio)
        h.tick()
        self.assertEqual([t for t in h.texts() if t.startswith("🟢")], [])
        signals = h.storage.pr_signals()
        self.assertEqual(len(signals), 1)
        self.assertIsNone(signals[0]["tg_message_id"])
        self.assertEqual(signals[0]["status"], "aberto")

    def test_history_before_tracking_is_not_a_paper_signal(self) -> None:
        h = self.h
        h.clock.advance(30 * H)                              # descoberto depois do rompimento
        start_tracking(h)
        h.run_hours(3)
        self.assertEqual(h.storage.pr_signals(), [])
        self.assertEqual([t for t in h.texts() if t.startswith(("👀", "🟢"))], [])
        closed = int((h.clock() - LAG_S - H - GRAD) // H) + 1             # candles fechados ate agora (+ folga)
        self.assertEqual(len(h.live.dets[("POOL1", "1h")].bars), closed)

    @unittest.skipUnless(charts.available(), "matplotlib nao instalado")
    def test_entry_alert_goes_with_a_chart_and_falls_back_to_text(self) -> None:
        h = self.h
        h.live.settings = LiveSettings(**{**h.settings.__dict__, "grafico": True})
        start_tracking(h)
        h.run_hours(24)
        self.assertEqual(len(h.tg.photos), 1)
        png, caption, keyboard, _ = h.tg.photos[0]
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertTrue(caption.startswith("🟢"))
        self.assertLessEqual(len(caption), 1024)
        self.assertIn("axiom.trade/meme/POOL1", json.dumps(keyboard))
        # foto recusada: o alerta sai em texto
        h2 = LiveHarness()
        try:
            h2.live.settings = h.live.settings
            h2.tg.fail_photo = True
            start_tracking(h2)
            h2.run_hours(24)
            self.assertEqual(len([t for t, _ in h2.tg.sent if t.startswith("🟢")]), 1)
        finally:
            h2.close()


class MultiTimeframeSolQuoteTest(unittest.TestCase):
    def test_lbc_from_1h_first_then_5m_and_4h_with_sol_converted_by_the_reference_pool(self) -> None:
        from ..pos_runner.quotes import REFERENCE_POOLS
        settings = LiveSettings(ligado=True, timeframes=("5m", "1h", "4h"), max_pools=5, chamadas_por_ciclo=6,
                                descoberta_min=3, fontes=("pumpswap",), grafico=False)
        h = LiveHarness(settings=settings, start=GRAD + 3 * H + 120)
        try:
            ref_pool, _side = REFERENCE_POOLS[SOL]
            sol_usd = 150.0
            h.world.series[(ref_pool, "1h")] = [Bar(GRAD - 30 * H + k * H, sol_usd, sol_usd, sol_usd, sol_usd, 1e6) for k in range(200)]
            mc = 400_000.0
            for tf, n in (("5m", 12 * 48), ("1h", 48), ("4h", 12)):
                step = tf_seconds(tf)
                first = GRAD // step * step                    # candles do GT alinhados ao timeframe (4h: 00h, 04h...)
                h.world.series[("POOL1", tf)] = [Bar(first + k * step, mc / SUPPLY / sol_usd, mc * 1.01 / SUPPLY / sol_usd,
                                                     mc * 0.99 / SUPPLY / sol_usd, mc / SUPPLY / sol_usd, 10.0) for k in range(n)]
            h.world.lists["networks/solana/dexes/pumpswap/pools"] = pools_json(
                [{"pool": "POOL1", "mint": "MINT1", "symbol": "CAT", "mc": mc, "created": GRAD + 60, "quote": SOL}])
            h.verifier.verify = lambda rpc, pool, mint, created, lp: Lineage("ok", "", "pumpfun", GRAD + 60, SOL, SUPPLY, "S", "MigrateV2")
            h.tick()
            h.verifier.step()
            for _ in range(13):                                  # passa do fechamento do 1o candle de 4h
                h.clock.advance(300)
                h.tick()
            row = h.storage.pr_pool("POOL1")
            self.assertAlmostEqual(row["l_bc"], mc, delta=1.0)                     # preco em SOL x SOL/USD x supply
            for tf in ("5m", "1h", "4h"):
                bars = h.storage.pr_bars("POOL1", tf)
                self.assertTrue(bars, tf)
                self.assertAlmostEqual(bars[-1][4], mc, delta=1.0)
                self.assertLessEqual(bars[-1][0] + tf_seconds(tf), h.clock() - LAG_S)
        finally:
            h.close()


class BudgetTest(unittest.TestCase):
    def test_never_spends_more_than_its_slice_nor_the_kept_calls(self) -> None:
        h = LiveHarness()
        try:
            for k in range(4):
                h.world.add_series(f"P{k}", "1h", textbook().bars)
            h.world.lists["networks/solana/dexes/pumpswap/pools"] = pools_json(
                [{"pool": f"P{k}", "mint": f"M{k}", "symbol": f"T{k}", "mc": 1e6, "created": GRAD + 60} for k in range(4)])
            h.tick()
            for _ in range(4):
                h.verifier.step()
            budget = CallBudget(4)
            out = h.live.tick(h.clock(), budget, keep=2)
            self.assertEqual(out["chamadas"], 2)               # 4 de orcamento, 2 guardadas para o v0
            self.assertEqual(budget.used, 2)
            budget = CallBudget(20)
            h.clock.advance(H)
            out = h.live.tick(h.clock(), budget, keep=1)
            self.assertLessEqual(out["chamadas"], h.settings.chamadas_por_ciclo)
        finally:
            h.close()

    def test_429_exhausts_the_cycle_and_is_reported(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.clock.advance(H)
            h.world.fail = RateLimited(30.0)
            budget = CallBudget(10)
            out = h.live.tick(h.clock(), budget, keep=1)
            self.assertTrue(out["rate_limited"])
            self.assertEqual(budget.left(), 0)
            h.clock.advance(H)
            h.tick()                                          # proximo ciclo segue normalmente
            self.assertGreater(len(h.storage.pr_bars("POOL1", "1h")), 9)
        finally:
            h.close()

    def test_failed_discovery_list_does_not_stop_the_refreshes(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            bars = len(h.storage.pr_bars("POOL1", "1h"))
            h.clock.advance(H)
            h.live.next_discovery = 0
            h.world.fail = ApiError("http", "GeckoTerminal: HTTP 502", 502)   # a lista de descoberta falha
            out = h.tick()
            self.assertEqual(out["erros"], 1)
            self.assertEqual(len(h.storage.pr_bars("POOL1", "1h")), bars + 1)
        finally:
            h.close()

    def test_api_error_on_one_pool_backs_off_without_stopping_the_tick(self) -> None:
        h = LiveHarness()
        try:
            start_tracking(h)
            h.clock.advance(H)
            h.live.next_discovery = h.clock() + 3600            # a falha cai no candle do pool, nao na lista
            h.world.fail = ApiError("http", "GeckoTerminal: HTTP 500", 500)
            out = h.tick()
            self.assertEqual(out["erros"], 1)
            self.assertGreater(h.live.sched[("POOL1", "1h")]["next"], h.clock())
        finally:
            h.close()


class ConfigSectionTest(unittest.TestCase):
    def test_shipped_section_is_valid_and_parsed(self) -> None:
        cfg = shipped_config()
        s = LiveSettings.from_config(cfg.raw["pos_runner"])
        self.assertTrue(s.ligado)
        self.assertEqual(s.timeframes, ("5m", "1h", "4h"))
        self.assertTrue(s.so_primario)
        self.assertFalse(LiveSettings.from_config(None).ligado)

    def test_invalid_values_are_reported(self) -> None:
        for patch in ({"timeframes": ["2h"]}, {"fontes": ["dexscreener"]}, {"max_pools": 0}, {"alertas": {"saida": "sim"}}):
            raw = copy.deepcopy(shipped_config().raw)
            section = raw["pos_runner"]
            for key, value in patch.items():
                if isinstance(value, dict):
                    section[key].update(value)
                else:
                    section[key] = value
            with self.assertRaises(ConfigError, msg=str(patch)):
                build_config(raw)
        raw = copy.deepcopy(shipped_config().raw)
        del raw["pos_runner"]
        build_config(raw)                                      # secao opcional


class EngineHookTest(unittest.TestCase):
    class Stub:
        def __init__(self, want: int):
            self.want = want
            self.ticks: list[tuple[int, int]] = []
            self.offers = 0

        def enabled(self) -> bool:
            return True

        def wanted(self, now: float) -> int:
            return self.want

        def offer(self, snaps, now, fonte="bot"):
            self.offers += 1
            return 0

        def tick(self, now, budget, keep):
            self.ticks.append((budget.left(), keep))
            budget.take(min(self.want, budget.left() - keep), keep=0)
            return {"chamadas": self.want, "erros": 0, "rate_limited": False}

        def update_settings(self, *a):
            pass

        def status_line(self) -> str:
            return "POS-RUNNER: stub"

    def test_engine_reserves_the_slice_and_calls_the_pos_runner_every_cycle(self) -> None:
        from .test_engine_e2e import happy
        quiet = Env()
        busy = Env()
        try:
            for k in range(40):                                # muitos pools jovens e candidatos: o v0 comeria tudo
                busy.gt.add(happy(pool=f"pool{k}", token=f"tok{k}", created_ts=busy.clock() - 60))
            for env, minimum in ((quiet, 3), (busy, 1)):
                stub = self.Stub(3)
                env.engine.pos_runner = stub
                env.cycle(3)
                self.assertEqual(len(stub.ticks), 3)
                self.assertEqual(stub.offers, 3)
                for left, keep in stub.ticks:
                    self.assertGreaterEqual(left - keep, minimum)  # quieto: a fatia inteira; ocupado: nunca passa fome
                self.assertIn("POS-RUNNER: stub", env.engine.status_text())
        finally:
            quiet.close()
            busy.close()


if __name__ == "__main__":
    unittest.main()
