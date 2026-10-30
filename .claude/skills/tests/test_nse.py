"""NSE (Indian stocks) mode and real trading costs across the pack: IST sessions 09:15-15:30, the NSE
holiday list, Rs 0.05 ticks, Zerodha intraday charges, and the dashboard paper broker. Offline, on 60
days of real 5-minute NSE bars saved on 2026-10-30 (tests/fixtures/nse/*.NS-60d5m.json.gz)."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

tm = load("trader-timemachine", "timemachine")
ex = load("trader-exit", "exit")
size = load("trader-budget", "size")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")
entry = load("trader-entry", "entry")
scan = load("trader-scanner", "scan")

NSE = os.path.join(FIX, "nse")
REL = os.path.join(NSE, "RELIANCE.NS-60d5m.json.gz")


def run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def cfg_file(d, **nse):
    path = os.path.join(d, "config.json")
    m = {"budget": 100000, "max_loss_per_trade_usd": 1000, "max_daily_loss_usd": 3000, "max_order_usd": 150000,
         "min_order_usd": 500, "max_position_pct": 100, "cash_buffer_pct": 0, "broker": "dashboard"}
    m.update(nse)
    with open(path, "w") as fh:
        json.dump({"paper": True, "markets": {"nse": m}}, fh)
    return path


# the real 2026-10-28 RELIANCE opening-range breakout: range 1187.00-1194.80, close 1199.60 at 09:45 IST
PLAN = {"symbol": "RELIANCE.NS", "side": "buy", "date": "2026-10-28", "setup": "orb", "entry": 1199.6,
        "stop": 1190.9, "target": 1217.0, "entry_time": "09:45", "flat_by": "15:10"}


class Reset(unittest.TestCase):
    def tearDown(self):
        for m in (tm, ex, entry, scan):
            m.set_market("us")
        size.set_market("AAPL")


class Costs(Reset):
    def test_zerodha_intraday_round_trip(self):
        # 114 shares, buy 1199.60, sell 1190.90: brokerage 20 + 20 (capped), STT 33.94, NSE 8.37,
        # SEBI 0.27, stamp 4.10, GST 18 % of (40 + 8.37 + 0.27) = 8.76 -> 95.44
        ex.set_market("nse")
        self.assertAlmostEqual(ex.round_trip_cost(1199.6, 1190.9, 114), 95.44, places=2)
        size.set_market("RELIANCE.NS", 1199.6)
        self.assertAlmostEqual(size.round_trip_cost(1199.6, 1190.9, 114), 95.44, places=2)
        self.assertAlmostEqual(check.round_trip_cost(1199.6, 1190.9, 114, "nse"), 95.44, places=2)

    def test_brokerage_is_capped_per_order(self):
        ex.set_market("nse")
        small = ex.round_trip_cost(1000, 1000, 10)          # 0.03 % of Rs 10,000 = Rs 3 a side
        big = ex.round_trip_cost(1000, 1000, 1000)          # 0.03 % of Rs 10 lakh = Rs 300 -> capped at 20
        self.assertLess(big / 1000, 3 * small / 10)

    def test_crypto_fee_and_no_cost_for_us(self):
        ex.set_market("crypto")
        self.assertAlmostEqual(ex.round_trip_cost(100, 110, 2, 0.1), 0.42)
        ex.set_market("us")
        self.assertEqual(ex.round_trip_cost(100, 110, 2), 0.0)


class Exit(Reset):
    def test_reliance_plan_in_rupees_with_charges(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = run(ex.main, ["plan", "--symbol", "RELIANCE.NS", "--entry", "1199.60", "--or-high", "1194.8",
                                         "--or-low", "1187", "--date", "2026-10-28", "--time", "09:45", "--target", "2R",
                                         "--now", "2026-10-28 09:46", "--config", cfg_file(d), "--json"])
        self.assertEqual(code, 0)
        p = json.loads(out)
        self.assertEqual((p["market"], p["stop"], p["target"], p["flat_by"], p["entry_time"]),
                         ("nse", 1190.9, 1217.0, "15:10", "09:45"))
        c = p["costs"]
        self.assertEqual((c["qty_est"], c["at_stop"], c["r_at_target_net"], c["r_at_stop_net"]), (114.0, 95.44, 1.903, -1.096))

    def test_stop_rounds_down_to_the_nse_tick(self):
        ex.set_market("nse")
        self.assertEqual(str(ex.floor_cents("1190.93")), "1190.90")
        self.assertEqual(str(ex.cents("1190.93")), "1190.95")

    def test_a_plan_that_is_mostly_charges_is_refused(self):
        # Rs 0.60 risk on a Rs 1,000 stock: one share's charges (~Rs 0.66) exceed it
        code, _, err = run(ex.main, ["plan", "--symbol", "TCS.NS", "--entry", "1000", "--stop", "price:999.4",
                                     "--setup", "level", "--date", "2026-10-28", "--time", "10:00",
                                     "--now", "2026-10-28 10:01", "--config", "/nonexistent"])
        self.assertEqual(code, 1)
        self.assertIn("the trade is mostly fees", err)


class TimeMachine(Reset):
    def test_reliance_replay_on_the_ist_session(self):
        code, out, _ = run(tm.main, ["run", "--symbol", "RELIANCE.NS", "--date", "2026-10-28", "--entry", "1199.60",
                                     "--stop", "1190.90", "--target", "1217.00", "--entry-time", "09:45",
                                     "--offline", NSE, "--now", "2026-10-30 12:00", "--json", "--plan", "/nonexistent"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual((doc["plan"]["entry_bar"], doc["mc"]["until"], doc["mc"]["bars_left"]), (5, "15:15", 66))
        self.assertEqual(doc["mc"]["pool_sessions"], 57)
        self.assertIn("IST", doc["data"]["last_bar"])
        h = doc["history"]
        self.assertEqual((h["triggered"], h["target"], h["stop"]), (26, 7, 13))
        self.assertGreater(h["avg_R"], 0)                     # +0.159 R before charges ...
        self.assertLess(h["avg_R_net"], h["avg_R"])            # ... less after them
        self.assertIn("after costs", doc["verdict"])


class Entry(Reset):
    def test_reliance_breakout_in_ist(self):
        code, out, _ = run(entry.main, ["check", "RELIANCE.NS", "--offline", REL, "--now", "2026-10-28 10:00", "--json",
                                        "--config", "/nonexistent"])
        r = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((r["opens"], r["opening_range"]["high"], r["trigger"]["time"], r["trigger"]["price"]),
                         ("09:15", 1194.8, "09:45", 1199.6))

    def test_nse_holiday_is_closed(self):
        _, out, _ = run(entry.main, ["check", "TCS.NS", "--offline", os.path.join(NSE, "TCS.NS-60d5m.json.gz"),
                                     "--now", "2026-10-20 10:00", "--json", "--config", "/nonexistent"])
        r = json.loads(out)
        self.assertEqual(r["phase"], "closed")
        self.assertIn("Dussehra", r["reason"])


class Budget(Reset):
    def test_max_loss_includes_charges(self):
        # 104 shares: 104 x 8.70 + 91.2 charges = 996 <= 1,000; 105 shares would be 1,004.9
        cfg = {"markets": {"nse": {"budget": 1000000, "max_loss_per_trade_usd": 1000, "max_order_usd": 10000000,
                                   "max_position_pct": 100, "cash_buffer_pct": 0, "broker": "dashboard"}}}
        s = size.size_trade(PLAN, cfg, today="2026-10-28")
        self.assertEqual((s["qty"], s["bound_by"]), (104, "max loss"))
        self.assertLessEqual(s["max_loss"], 1000)
        o = size.bracket_order(s)
        self.assertEqual((o["broker"], o["symbol"], o["order_class"], o["stop_loss_stop_price"]),
                         ("dashboard", "RELIANCE.NS", "bracket", "1190.90"))


class Risk(unittest.TestCase):
    ORDER = {"symbol": "RELIANCE.NS", "side": "buy", "qty": "83", "type": "market", "time_in_force": "day",
             "order_class": "bracket", "take_profit_limit_price": "1217.00", "stop_loss_stop_price": "1190.90",
             "broker": "dashboard", "plan": {"entry": 1199.6, "stop": 1190.9, "target": 1217.0}}
    CFG = {"markets": {"nse": {"budget": 100000, "max_loss_per_trade_usd": 1000, "max_order_usd": 150000,
                               "max_position_pct": 100, "cash_buffer_pct": 0, "broker": "dashboard"}}}

    def one(self, utc):
        return check.check([self.ORDER], self.CFG, now=check.parse_now(utc + "Z"))["results"][0]

    def test_passes_in_the_ist_window_with_charges(self):
        r = self.one("2026-10-28 04:16")          # 09:46 IST
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        # 83 x 8.70 + 82.32 charges = 804.42; (17.40 x 83 - 82.94) / 804.42 = 1.69 after charges
        self.assertEqual((r["max_loss"], r["reward_risk"]), (804.42, 1.69))

    def test_windows_holidays_and_weekends(self):
        self.assertIn("before 09:30 IST", " ".join(self.one("2026-10-28 03:50")["reasons"]))
        self.assertIn("after 14:45 IST", " ".join(self.one("2026-10-28 09:30")["reasons"]))
        self.assertIn("Dussehra", " ".join(self.one("2026-10-20 05:00")["reasons"]))
        self.assertIn("weekend", " ".join(self.one("2026-10-31 05:00")["reasons"]))


class Broker(unittest.TestCase):
    def test_dashboard_order_body(self):
        o = dict(Risk.ORDER, plan={"setup": "orb"})
        self.assertEqual(ticket.dashboard_input(o), {"symbol": "RELIANCE.NS", "side": "BUY", "order_type": "MARKET",
                                                     "quantity": 83.0, "stop_loss": 1190.9, "target": 1217.0,
                                                     "tag": "SKILL_ORB"})
        self.assertEqual(ticket.canon("NSE:TCS"), "TCS.NS")

    def test_send_needs_a_risk_pass_and_a_yes(self):
        with tempfile.TemporaryDirectory() as d:
            orders = os.path.join(d, "orders.json")
            with open(orders, "w") as fh:
                json.dump({"orders": [Risk.ORDER]}, fh)
            code, _, err = run(ticket.main, ["send", "--index", "1", "--orders", orders, "--config", "/nonexistent",
                                             "--risk", os.path.join(d, "risk.json"), "--state", os.path.join(d, "b.json")])
        self.assertEqual(code, 1)
        self.assertIn("not cleared by trader-risk", err)


class Scanner(Reset):
    def test_offline_orb_replay_in_ist(self):
        code, out, _ = run(scan.main, ["orb", "--market", "nse", "--offline", NSE, "--now", "2026-10-28 10:15",
                                       "--no-write", "--json"])
        doc = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(doc["as_of"], "2026-10-28 10:15 IST")
        hits = {h["symbol"]: h for h in doc["hits"]}
        self.assertEqual(hits["RELIANCE.NS"]["or_high"], 1194.8)
        self.assertEqual(hits["RELIANCE.NS"]["at"], "09:45")

    def test_symbols_with_ampersands_are_quoted(self):
        scan.set_market("nse")
        self.assertIn("M%26M.NS", scan.spark_path(["M&M.NS", "TCS.NS"], "1d", "5m"))
        self.assertEqual(len(scan.NSE_UNIVERSE), 38)


if __name__ == "__main__":
    unittest.main()
