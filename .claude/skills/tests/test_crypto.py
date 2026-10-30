"""Crypto mode across the pack: 24/7 UTC sessions, coin precision, fractional sizing and
Alpaca's crypto order rules. Offline, on 60 days of real 5-minute bars saved on 2026-10-29
(tests/fixtures/crypto/*-60d5m.json.gz)."""

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
alerts = load("trader-alerts", "alerts")
entry = load("trader-entry", "entry")
scan = load("trader-scanner", "scan")

CRYPTO = os.path.join(FIX, "crypto")
BTC_FILE = os.path.join(CRYPTO, "BTC-USD-60d5m.json.gz")
DOGE_FILE = os.path.join(CRYPTO, "DOGE-USD-60d5m.json.gz")
ETH_FILE = os.path.join(CRYPTO, "ETH-USD-60d5m.json.gz")


def run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def btc_plan(**over):
    p = {"symbol": "BTC-USD", "side": "buy", "date": "2026-10-28", "setup": "orb", "entry": 80842.5,
         "stop": 80709.47, "target": 80975.53, "entry_time": "01:45", "flat_by": "23:55"}
    p.update(over)
    return p


def btc_order(**over):
    o = {"symbol": "BTC/USD", "side": "buy", "qty": "0.04638", "type": "market", "time_in_force": "gtc",
         "order_class": "simple", "plan": {"entry": 80842.5, "stop": 80709.47, "target": 80975.53}}
    o.update(over)
    return o


def utc(text):
    return check.parse_now(text + "Z")


class Reset(unittest.TestCase):
    def tearDown(self):
        for m in (tm, ex, size, entry, scan):
            m.set_market("us") if m is not size else size.set_market("AAPL")


class Symbols(Reset):
    def test_pairs_are_crypto_and_tickers_are_not(self):
        for m in (tm, ex, size, check, ticket, alerts, entry, scan):
            for s in ("BTC-USD", "BTC/USD", "eth-usdt", "SOLUSDT", "DOGE-USDC"):
                self.assertTrue(m.is_crypto(s), (m.__name__, s))
            for s in ("AAPL", "BRK.B", "TSLA", "USD", ""):
                self.assertFalse(m.is_crypto(s), (m.__name__, s))

    def test_yahoo_and_alpaca_spellings(self):
        self.assertEqual(tm.yahoo_symbol("BTC/USD"), "BTC-USD")
        self.assertEqual(entry.yahoo_symbol("DOGEUSDT"), "DOGE-USD")
        self.assertEqual(scan.to_yahoo("eth-usdc"), "ETH-USD")
        self.assertEqual(tm.yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(size.broker_symbol("BTC-USD"), "BTC/USD")
        self.assertEqual(size.broker_symbol("SOLUSDT"), "SOL/USDT")
        self.assertEqual(check.canon("DOGE-USD"), "DOGE/USD")
        self.assertEqual(ticket.canon("TSLA"), "TSLA")


class TimeMachine(Reset):
    ARGS = ["run", "--offline", CRYPTO, "--now", "2026-10-30 12:00", "--json", "--plan", "/nonexistent"]

    def test_btc_replays_a_full_utc_day(self):
        code, out, _ = run(tm.main, self.ARGS + ["--symbol", "BTC/USD", "--date", "2026-10-28", "--entry", "80842.50",
                                                  "--stop", "80709.46", "--target", "80975.54", "--entry-time", "01:45"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["plan"]["entry_bar"], 20)        # 01:40 bar of a session that starts 00:00 UTC
        self.assertEqual(doc["mc"]["until"], "24:00")
        self.assertEqual(doc["mc"]["bars_left"], 267)
        self.assertEqual(doc["mc"]["pool_sessions"], 58)
        self.assertAlmostEqual(doc["mc"]["p_target"], 0.483, places=3)
        self.assertAlmostEqual(doc["mc"]["p_stop"], 0.517, places=3)
        h = doc["history"]
        self.assertEqual((h["triggered"], h["target"], h["stop"]), (53, 21, 32))
        self.assertIn("UTC", doc["data"]["last_bar"])

    def test_cheap_coin_keeps_its_decimals(self):
        code, out, _ = run(tm.main, self.ARGS + ["--symbol", "DOGEUSDT", "--date", "2026-10-28", "--entry", "0.07908",
                                                  "--stop", "0.078894", "--target", "0.079266", "--entry-time", "01:25"])
        doc = json.loads(out)
        self.assertEqual(doc["plan"]["risk_per_share"], 0.000186)
        self.assertNotEqual(doc["mc"]["median_close"], 0.08)   # not rounded to the cent

    def test_24h_clock_has_no_pm_guess(self):
        tm.set_market("crypto")
        self.assertEqual(tm.parse_clock("03:55", "x"), 3 * 60 + 55)
        tm.set_market("us")
        self.assertEqual(tm.parse_clock("3:55", "x"), 15 * 60 + 55)


class Exit(Reset):
    def test_doge_orb_plan_is_mostly_fees_and_refused(self):
        # the real 2026-10-28 DOGE breakout: risk 0.000185 a coin, 0.1 % fee each way = 0.000158 (85 %)
        code, _, err = run(ex.main, ["plan", "--symbol", "DOGE/USD", "--entry", "0.07908", "--or-high", "0.07899",
                                     "--or-low", "0.07880", "--date", "2026-10-28", "--time", "01:25", "--target", "2R",
                                     "--now", "2026-10-28 01:26", "--json", "--config", "/nonexistent"])
        self.assertEqual(code, 1)
        self.assertIn("85 % of the $0.000185 risk: the trade is mostly fees", err)

    def test_doge_wide_plan_rounds_to_the_coin_tick(self):
        code, out, _ = run(ex.main, ["plan", "--symbol", "DOGE/USD", "--entry", "0.07908", "--stop", "pct:2",
                                     "--setup", "level", "--date", "2026-10-28", "--time", "01:25", "--target", "2R",
                                     "--now", "2026-10-28 01:26", "--json", "--config", "/nonexistent"])
        self.assertEqual(code, 0)
        p = json.loads(out)
        self.assertEqual((p["stop"], p["target"], p["risk_per_share"]), (0.077498, 0.082244, 0.001582))
        self.assertEqual((p["market"], p["flat_by"], p["created_at"]), ("crypto", "23:55", "2026-10-28T01:26:00Z"))
        self.assertEqual(p["costs"]["share_of_risk"], 0.099)

    def test_btc_atr_stop_reads_the_utc_session(self):
        # 21 bars closed by 01:46 UTC; ATR(14) 87.8415. A 1.5 ATR stop (risk 131.77) is less than the
        # 161.55 round-trip fee, so it is refused; a 3 ATR stop is the first one the fees leave room for.
        code, _, err = run(ex.main, ["plan", "--symbol", "BTC-USD", "--entry", "80842.50", "--date", "2026-10-28",
                                     "--time", "01:45", "--setup", "level", "--stop", "atr:1.5", "--offline", BTC_FILE,
                                     "--now", "2026-10-28 01:46", "--json", "--config", "/nonexistent"])
        self.assertEqual(code, 1)
        self.assertIn("123 % of the $131.77 risk", err)
        code, out, _ = run(ex.main, ["plan", "--symbol", "BTC-USD", "--entry", "80842.50", "--date", "2026-10-28",
                                     "--time", "01:45", "--setup", "level", "--stop", "atr:4", "--offline", BTC_FILE,
                                     "--now", "2026-10-28 01:46", "--json", "--config", "/nonexistent"])
        self.assertEqual(code, 0)
        p = json.loads(out)
        self.assertEqual(p["atr_bars"], 14)
        self.assertEqual(p["stop"], 80491.13)   # 80842.50 - 4 x 87.8415, rounded down

    def test_us_config_flat_by_does_not_cut_a_coin_trade(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "config.json")
            with open(cfg, "w") as fh:
                json.dump({"flat_by": "15:55"}, fh)
            code, out, _ = run(ex.main, ["plan", "--symbol", "ETH-USD", "--entry", "2400", "--setup", "level",
                                         "--stop", "pct:1", "--date", "2026-10-28", "--time", "18:00",
                                         "--now", "2026-10-28 18:01", "--json", "--config", cfg])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["flat_by"], "23:55")


class Budget(Reset):
    CFG = {"budget": 5000}

    def test_btc_is_sized_in_fractions_without_a_bracket(self):
        s = size.size_trade(btc_plan(), self.CFG, today="2026-10-28")
        # max loss = 0.04638 x 133.03 risk (6.17) + 0.1 % fee on both legs (7.49) = 13.66
        self.assertEqual((s["qty"], s["bound_by"], s["max_loss"]), (0.04638, "position cap", 13.66))
        o = size.bracket_order(s)
        self.assertEqual((o["symbol"], o["qty"], o["time_in_force"], o["order_class"]),
                         ("BTC/USD", "0.04638", "gtc", "simple"))
        self.assertNotIn("stop_loss_stop_price", o)
        self.assertEqual(o["plan"]["stop"], 80709.47)

    def test_doge_risk_is_not_rounded_to_zero(self):
        plan = btc_plan(symbol="DOGEUSDT", entry=0.07908, stop=0.078895, target=0.07945)
        s = size.size_trade(plan, self.CFG, today="2026-10-28")
        self.assertEqual((s["risk_per_share"], s["qty"]), (0.000185, 47420))
        self.assertEqual(size.bracket_order(s)["symbol"], "DOGE/USDT")

    def test_stocks_still_whole_shares(self):
        plan = {"symbol": "TSLA", "entry": 364.18, "stop": 358.32, "target": 370.04, "date": "2026-10-19"}
        s = size.size_trade(plan, self.CFG, today="2026-10-19")
        self.assertEqual(s["qty"], 8)
        self.assertEqual(size.bracket_order(s)["order_class"], "bracket")


class Risk(unittest.TestCase):
    SAT = utc("2026-10-31 14:00")

    def cfg(self, **over):
        c = {"budget": 5000, "allow_crypto": True}
        c.update(over)
        return c

    def one(self, order, **over):
        return check.check([order], self.cfg(**over), now=self.SAT)["results"][0]

    def test_off_by_default(self):
        r = check.check([btc_order()], {"budget": 5000}, now=self.SAT)["results"][0]
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn('"allow_crypto": true', " ".join(r["reasons"]))

    def test_a_1r_target_that_fees_eat_is_blocked(self):
        # 1R target worth $6.17, round-trip fees $7.50: even a winner loses, reward:risk after fees -0.10
        r = self.one(btc_order())
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertEqual((r["max_loss"], r["reward_risk"]), (13.66, -0.1))

    def test_passes_on_a_saturday_with_a_plan_stop_warning(self):
        # 2 % stop, 4 % target: loss 5.66 + 0.56 fees = 6.22; (11.32 - 0.58) / 6.22 = 1.73 after fees
        wide = btc_order(qty="0.0035", plan={"entry": 80842.5, "stop": 79225.65, "target": 84076.2})
        r = self.one(wide)
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual((r["max_loss"], r["reward_risk"]), (6.22, 1.73))
        self.assertTrue(any("not at the broker" in w for w in r["warnings"]))
        self.assertFalse(any("advanced order" in w for w in r["warnings"]))

    def test_us_stock_on_a_saturday_is_still_blocked(self):
        o = {"symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
             "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32",
             "plan": {"entry": 364.18, "stop": 358.32, "target": 370.04}}
        r = self.one(o)
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("market is closed", " ".join(r["reasons"]))

    def test_alpaca_crypto_rules(self):
        self.assertIn("gtc or ioc", " ".join(self.one(btc_order(time_in_force="day"))["reasons"]))
        self.assertIn("market, limit or stop_limit", " ".join(self.one(btc_order(type="stop", stop_price="80000"))["reasons"]))
        bracket = btc_order(order_class="bracket", take_profit_limit_price="80975.53", stop_loss_stop_price="80709.47")
        self.assertIn("no bracket orders for crypto", " ".join(self.one(bracket)["reasons"]))

    def test_tiny_stop_is_measured_at_the_coin_tick(self):
        o = {"symbol": "DOGE/USD", "side": "buy", "qty": "47420", "type": "market", "time_in_force": "gtc",
             "plan": {"entry": 0.07908, "stop": 0.078895, "target": 0.07945}}
        r = self.one(o)
        # measured at the coin's tick, not the cent: risk 0.000185 a coin. Fees (0.1 % a side) make
        # the loss 8.77 + 7.49 = 16.26 and leave reward:risk 0.62, under the minimum 1: blocked.
        self.assertEqual((r["risk_per_share"], r["max_loss"], r["reward_risk"]), (0.000185, 16.26, 0.62))
        self.assertEqual(r["verdict"], "BLOCK")

    def test_optional_utc_window(self):
        r = self.one(btc_order(), crypto_no_entries_after="12:00")
        self.assertIn("no new crypto entries after 12:00 UTC", " ".join(r["reasons"]))


class Broker(unittest.TestCase):
    def test_tool_and_fields(self):
        o = btc_order()
        self.assertEqual(ticket.tool_name(o), "place_crypto_order")
        self.assertEqual(ticket.tool_input(o), {"symbol": "BTC/USD", "side": "buy", "qty": "0.04638",
                                                "type": "market", "time_in_force": "gtc"})
        self.assertEqual(ticket.tool_name({"symbol": "TSLA"}), "place_stock_order")

    def test_a_yes_must_name_the_exact_coin_amount(self):
        self.assertFalse(ticket.parse_yes("yes 0.046", btc_order())[0])
        self.assertTrue(ticket.parse_yes("yes 0.04638", btc_order())[0])
        self.assertTrue(ticket.parse_yes("yes", btc_order())[0])

    def test_flatten_is_a_gtc_sell(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "orders.json")
            code, _, _ = run(ticket.main, ["flatten", "--symbol", "BTC-USD", "--qty", "0.04638", "--orders", out,
                                           "--now", "2026-10-28 23:56Z", "--config", "/nonexistent",
                                           "--plan", "/nonexistent"])
            self.assertEqual(code, 0)
            with open(out) as fh:
                o = json.load(fh)["orders"][0]
        self.assertEqual((o["symbol"], o["side"], o["time_in_force"]), ("BTC/USD", "sell", "gtc"))


class Alerts(unittest.TestCase):
    def test_plan_rules_run_on_utc(self):
        rules = alerts.rules_from_plan(btc_plan(), cfg_flat_by="15:55")
        flat = [r for r in rules if r["type"] == "time"][0]
        self.assertEqual((flat["at"], flat.get("tz")), ("23:55", "UTC"))
        self.assertNotIn("before_close", flat)

    def test_flat_by_rings_on_a_saturday_and_stop_says_sell(self):
        now = alerts.parse_now("2026-10-31T23:56:00Z")
        rules = alerts.rules_from_plan(btc_plan(date="2026-10-31"))
        quotes = {"BTC-USD": {"price": 80000.0}}
        rings, _ = alerts.evaluate(rules, quotes, alerts.market_status(now), {}, now)
        text = " ".join(r["message"] for r in rings)
        self.assertIn("23:56 UTC", text)
        self.assertIn("NOT at the broker", text)


class Entry(Reset):
    def check(self, sym, path, now):
        code, out, _ = run(entry.main, ["check", sym, "--offline", path, "--now", now, "--json",
                                        "--config", "/nonexistent"])
        return code, json.loads(out)

    def test_btc_breakout_on_the_utc_session(self):
        code, r = self.check("BTC/USD", BTC_FILE, "2026-10-28 02:00")
        self.assertEqual(code, 0)
        self.assertEqual(r["opening_range"]["high"], 80795.53)
        self.assertEqual((r["trigger"]["bar_index"], r["trigger"]["price"], r["trigger"]["time"]), (20, 80842.5, "01:45"))
        self.assertEqual(r["closes"], "24:00")

    def test_doge_levels_keep_their_decimals(self):
        code, r = self.check("DOGEUSDT", DOGE_FILE, "2026-10-28 01:30")
        self.assertEqual(r["opening_range"]["high"], 0.07899)

    def test_a_sunday_is_a_trading_day(self):
        code, r = self.check("ETH-USD", ETH_FILE, "2026-10-25 00:12")
        self.assertEqual(r["phase"], "forming")

    def test_mixed_watchlist_is_refused(self):
        with self.assertRaises(entry.EntryError):
            entry.market_of(["BTC-USD", "TSLA"])


class Scanner(Reset):
    def bars(self, day, skip=()):
        return [{"start": scan.slot(day, k)} for k in range(30) if k not in skip]

    def test_a_data_gap_is_tolerated_for_crypto_only(self):
        import datetime
        day = datetime.date(2026, 10, 28)
        scan.set_market("crypto")
        cutoff = scan.slot(day, 30)
        self.assertTrue(scan.usable(self.bars(day, skip={10}), day, cutoff, 3))
        self.assertFalse(scan.usable(self.bars(day, skip={1}), day, cutoff, 3))       # gap inside the range
        self.assertFalse(scan.usable(self.bars(day, skip={10, 11, 12, 13}), day, cutoff, 3))
        scan.set_market("us")
        cutoff = scan.slot(day, 30)
        self.assertFalse(scan.usable(self.bars(day, skip={10}), day, cutoff, 3))

    def test_default_universe_is_checked_coins(self):
        self.assertEqual(len(scan.CRYPTO_UNIVERSE), 23)
        for bad in ("TON-USD", "ARB-USD", "SHIB-USD"):
            self.assertNotIn(bad, scan.CRYPTO_UNIVERSE)


if __name__ == "__main__":
    unittest.main()
