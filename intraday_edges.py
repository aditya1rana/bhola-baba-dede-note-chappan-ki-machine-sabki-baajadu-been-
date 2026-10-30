"""
More intraday edge sources, tested on long histories with real charges.

NSE: ~3 years of hourly bars (Yahoo) for the 38 large caps and NIFTY. Bars open 09:15, 10:15 ... 15:15;
every trade is flat at the 15:15 open (before the 15:20 broker square-off). Zerodha intraday charges,
Rs 50,000 a leg.
Crypto: hourly Binance spot bars since 2023 for the 23 coins, long only (spot cannot short), 0.1 % a side.

A rule passes only if its average daily return after charges is above 0 in EACH of three equal time
slices and its t-stat over the whole sample is above 2. Everything else is noise or a loser.

Usage: python intraday_edges.py      (caches downloads in trader/research/)
"""

import json
import os
import sys
import time
import urllib.request

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".claude", "skills", "trader-scanner"))
from scan import NSE_UNIVERSE, CRYPTO_UNIVERSE  # noqa: E402
from intraday_research import charges  # noqa: E402

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trader", "research")
LEG = 50000.0
CRYPTO_FEE = 0.001


def nse_hourly(sym):
    p = os.path.join(CACHE, "h_" + sym.replace("&", "_").replace("^", "") + ".pkl")
    if os.path.exists(p):
        return pd.read_pickle(p)
    df = yf.download(sym, period="730d", interval="60m", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.to_pickle(p)
    return df


def binance_hourly(sym):
    pair = sym.replace("-USD", "USDT")
    p = os.path.join(CACHE, "b_" + pair + ".pkl")
    if os.path.exists(p):
        return pd.read_pickle(p)
    rows, start = [], int(pd.Timestamp("2023-01-01").timestamp() * 1000)
    while True:
        url = "https://api.binance.com/api/v3/klines?symbol=%s&interval=1h&limit=1000&startTime=%d" % (pair, start)
        chunk = json.load(urllib.request.urlopen(url, timeout=20))
        if not chunk:
            break
        rows += chunk
        start = chunk[-1][0] + 3600000
        if len(chunk) < 1000:
            break
        time.sleep(0.15)
    df = pd.DataFrame([r[:5] for r in rows], columns=["t", "Open", "High", "Low", "Close"]).astype(float)
    df.index = pd.to_datetime(df["t"], unit="ms")
    df = df.drop(columns="t")
    df.to_pickle(p)
    return df


def nse_table():
    """day x stock: prev close, 09:15 open, 10:15 / 11:15 / 14:15 prices, 15:15 open (the exit)."""
    rec = {}
    for sym in NSE_UNIVERSE + ["^NSEI"]:
        df = nse_hourly(sym)
        prev = None
        for day, d in df.groupby(df.index.date):
            t = {ts.strftime("%H:%M"): row for ts, row in d.iterrows()}
            if not all(k in t for k in ("09:15", "10:15", "11:15", "14:15", "15:15")):
                prev = d["Close"].iloc[-1]
                continue
            rec[(day, sym)] = {"prev": prev, "open": t["09:15"]["Open"], "p1015": t["10:15"]["Open"],
                               "p1115": t["11:15"]["Open"], "p1415": t["14:15"]["Open"], "exit": t["15:15"]["Open"],
                               "hi1": t["09:15"]["High"], "lo1": t["09:15"]["Low"]}
            prev = d["Close"].iloc[-1]
        print("\rNSE %s" % sym.ljust(14), end="", flush=True)
    print()
    return pd.DataFrame.from_dict(rec, orient="index").rename_axis(["day", "sym"]).dropna()


def leg_ret(entry, exit_, side):
    """Net return of one Rs 50,000 leg, as a fraction of the leg."""
    qty = max(1, int(LEG / entry))
    buy, sell = (entry, exit_) if side == 1 else (exit_, entry)
    gross = (exit_ - entry) * side * qty
    return (gross - charges(buy, sell, qty)) / (qty * entry)


def nse_rules(t):
    out = {}
    nifty = t.xs("^NSEI", level="sym")
    stocks = t.drop(index="^NSEI", level="sym")
    for day, g in stocks.groupby(level="day"):
        g = g.droplevel("day")
        if len(g) < 30 or day not in nifty.index:
            continue
        n = nifty.loc[day]
        r_open_1015 = g.p1015 / g.open - 1
        r_prev_1115 = g.p1115 / g.prev - 1
        n_prev_1115 = n.p1115 / n.prev - 1
        n_prev_1415 = n.p1415 / n.prev - 1
        gap = g.open / g.prev - 1
        rs = r_prev_1115 - n_prev_1115

        def basket(name, syms, col, side):
            out.setdefault(name, {})[day] = np.mean([leg_ret(g.loc[s, col], g.loc[s, "exit"], side) for s in syms])

        top, bot = r_open_1015.nlargest(3).index, r_open_1015.nsmallest(3).index
        basket("nse_first_hour_winners_long", top, "p1015", 1)
        basket("nse_first_hour_losers_long", bot, "p1015", 1)
        basket("nse_first_hour_winners_short", top, "p1015", -1)
        basket("nse_first_hour_losers_short", bot, "p1015", -1)
        basket("nse_rel_strength_long_1115", rs.nlargest(3).index, "p1115", 1)
        basket("nse_rel_weakness_short_1115", rs.nsmallest(3).index, "p1115", -1)
        # market intraday momentum: the day's direction so far (to 14:15) continues into the last hour
        side = 1 if n_prev_1415 > 0 else -1
        basket("nse_last_hour_with_market", (rs.nlargest(3) if side == 1 else rs.nsmallest(3)).index, "p1415", side)
        if abs(n_prev_1415) > 0.005:
            basket("nse_last_hour_with_market_big", (rs.nlargest(3) if side == 1 else rs.nsmallest(3)).index, "p1415", side)
        # gaps over 1.5 %: fade or follow from 10:15
        up, dn = gap[gap > 0.015].index, gap[gap < -0.015].index
        if len(up):
            basket("nse_gap_up_fade_short", up, "p1015", -1)
            basket("nse_gap_up_follow_long", up, "p1015", 1)
        if len(dn):
            basket("nse_gap_down_fade_long", dn, "p1015", 1)
        # first-hour range breakout on the hourly close, trend day filter: NIFTY above its first hour too
        brk = g[(g.p1115 > g.hi1) & (n.p1115 > n.hi1)]
        if len(brk):
            basket("nse_hour_range_break_long_mkt", brk.index[:3], "p1115", 1)
    return {k: pd.Series(v) for k, v in out.items()}


def crypto_rules():
    closes, opens = {}, {}
    for sym in CRYPTO_UNIVERSE:
        try:
            df = binance_hourly(sym)
        except Exception as e:   # a coin Binance does not list
            print("skip", sym, e)
            continue
        closes[sym], opens[sym] = df["Close"], df["Open"]
        print("\rcrypto %s %d bars" % (sym.ljust(10), len(df)), end="", flush=True)
    print()
    C, O = pd.DataFrame(closes), pd.DataFrame(opens)
    out = {}
    fee = 2 * CRYPTO_FEE
    days = sorted(set(C.index.normalize()))
    for day in days[1:]:
        t0, t_end = day, day + pd.Timedelta(hours=23)          # in at the 00:00 open, out at the 23:00 open
        prev24 = day - pd.Timedelta(hours=24)
        if t0 not in O.index or t_end not in O.index or prev24 not in O.index:
            continue
        o0, o_end, o_prev = O.loc[t0], O.loc[t_end], O.loc[prev24]
        ok = o0.notna() & o_end.notna() & o_prev.notna()
        r24 = (o0 / o_prev - 1)[ok]
        day_ret = (o_end / o0 - 1)[ok]
        if len(r24) < 10:
            continue

        def put(name, syms):
            out.setdefault(name, {})[day] = day_ret[syms].mean() - fee

        put("crypto_24h_winners_long", r24.nlargest(3).index)
        put("crypto_24h_losers_long", r24.nsmallest(3).index)
        if "BTC-USD" in r24.index:
            if r24["BTC-USD"] > 0:
                put("crypto_btc_after_up_day", ["BTC-USD"])
            if r24["BTC-USD"] < -0.03:
                put("crypto_btc_after_drop_3pct", ["BTC-USD"])
            if r24.mean() < -0.05:
                put("crypto_basket_after_crash_5pct", list(r24.index))
        # US session: 13:00-21:00 UTC long BTC
        a, b = day + pd.Timedelta(hours=13), day + pd.Timedelta(hours=21)
        if a in O.index and b in O.index and "BTC-USD" in O.columns:
            out.setdefault("crypto_btc_us_session", {})[day] = O.loc[b, "BTC-USD"] / O.loc[a, "BTC-USD"] - 1 - fee
        # Asia session: 00:00-08:00 UTC long BTC
        a, b = day, day + pd.Timedelta(hours=8)
        if b in O.index and "BTC-USD" in O.columns:
            out.setdefault("crypto_btc_asia_session", {})[day] = O.loc[b, "BTC-USD"] / O.loc[a, "BTC-USD"] - 1 - fee
    return {k: pd.Series(v) for k, v in out.items()}


def judge(series):
    rows = []
    for name, s in series.items():
        s = s.dropna().sort_index()
        if len(s) < 30:
            continue
        thirds = [x.mean() for x in np.array_split(s.values, 3)]
        t = s.mean() / (s.std(ddof=1) / np.sqrt(len(s))) if s.std() > 0 else 0
        eq = (1 + s).cumprod()
        rows.append({"rule": name, "days": len(s), "avg_bps": round(1e4 * s.mean(), 1), "win%": round(100 * (s > 0).mean(), 1),
                     "t": round(t, 2), "third1": round(1e4 * thirds[0], 1), "third2": round(1e4 * thirds[1], 1),
                     "third3": round(1e4 * thirds[2], 1), "max_dd%": round(100 * (eq / eq.cummax() - 1).min(), 1),
                     "from": str(s.index[0])[:10], "pass": all(x > 0 for x in thirds) and t > 2})
    return pd.DataFrame(rows).sort_values("avg_bps", ascending=False)


def main():
    os.makedirs(CACHE, exist_ok=True)
    pd.set_option("display.width", 220)
    nse = judge(nse_rules(nse_table()))
    print("\nNSE, hourly, after Zerodha intraday charges, Rs 50,000 a leg (bps = 1/100 of 1 % per day traded)")
    print(nse.to_string(index=False))
    cr = judge(crypto_rules())
    print("\nCrypto, hourly Binance spot, long only, after 0.1 % a side")
    print(cr.to_string(index=False))
    allr = pd.concat([nse, cr])
    allr.to_csv(os.path.join(CACHE, "edges_summary.csv"), index=False)
    print("\nPASS (positive in all three time slices, t > 2):", ", ".join(allr[allr["pass"]].rule) or "none")


if __name__ == "__main__":
    main()
