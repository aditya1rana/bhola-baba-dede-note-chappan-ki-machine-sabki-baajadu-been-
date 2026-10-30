"""
Intraday rule research on NSE 5-minute bars (Yahoo keeps 60 days), with Zerodha intraday charges.

Every rule risks Rs 1,000 a trade (quantity = 1000 / risk per share), enters on a 5-minute CLOSE,
checks the stop before the target inside a bar, and is flat at 15:10 IST. Long and short.
A rule counts only if its average R after charges is above 0 in BOTH halves of the sample
(first 30 trading days, last 30) - a rule that only worked in one half is luck.

Usage: python intraday_research.py            (downloads, then caches in trader/research/)
"""

import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".claude", "skills", "trader-scanner"))
from scan import NSE_UNIVERSE  # noqa: E402

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trader", "research")
RISK = 1000.0


def charges(buy, sell, qty):
    """Zerodha intraday equity, one round trip (same as the skills' round_trip_cost)."""
    bt, st = buy * qty, sell * qty
    brok = min(20.0, 0.0003 * bt) + min(20.0, 0.0003 * st)
    stt = 0.00025 * st
    txn = 0.0000307 * (bt + st)
    sebi = 0.000001 * (bt + st)
    stamp = 0.00003 * bt
    gst = 0.18 * (brok + txn + sebi)
    return brok + stt + txn + sebi + stamp + gst


def load(sym):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, sym.replace("&", "_") + ".pkl")
    if os.path.exists(p):
        return pd.read_pickle(p)
    df = yf.download(sym, period="60d", interval="5m", progress=False, auto_adjust=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.to_pickle(p)
    return df


def walk(bars, i, side, entry, stop, target):
    """From bar i+1 to 15:10: (exit price, how). Stop first inside a bar."""
    for j in range(i + 1, len(bars)):
        t, o, h, l, c = bars[j]
        if t >= "15:10":
            return o, "flat"
        if side == 1:
            if l <= stop:
                return min(o, stop), "stop"
            if h >= target:
                return max(o, target), "target"
        else:
            if h >= stop:
                return max(o, stop), "stop"
            if l <= target:
                return min(o, target), "target"
    return bars[-1][4], "flat"


def trade(day, sym, bars, i, side, stop, target_r, rule):
    t, _, _, _, entry = bars[i]
    risk = (entry - stop) * side
    if risk <= entry * 0.001:          # stop closer than 0.1 %: charges would eat it
        return None
    target = entry + side * target_r * risk
    exit_px, how = walk(bars, i, side, entry, stop, target)
    qty = max(1, int(RISK / risk))
    gross = (exit_px - entry) * side * qty
    buy, sell = (entry, exit_px) if side == 1 else (exit_px, entry)
    net = gross - charges(buy, sell, qty)
    return {"rule": rule, "day": day, "sym": sym, "time": t, "side": side, "R_gross": gross / (risk * qty),
            "R_net": net / (risk * qty), "net": net, "how": how}


def day_rules(sym, day, d, prev):
    """All rules on one stock-day. d: that day's bars; prev: previous day's (high, low, close)."""
    bars = [(ts.strftime("%H:%M"), *row) for ts, row in zip(d.index, d[["Open", "High", "Low", "Close"]].values)]
    times = [b[0] for b in bars]
    if len(bars) < 60 or times[0] != "09:15":
        return []
    out = []
    o_hi = max(b[2] for b in bars[:3])
    o_lo = min(b[3] for b in bars[:3])
    o_mid = (o_hi + o_lo) / 2
    tp = (d["High"] + d["Low"] + d["Close"]) / 3
    vwap = ((tp * d["Volume"]).cumsum() / d["Volume"].cumsum().replace(0, np.nan)).values
    day_open = bars[0][1]
    done = set()

    def once(rule, i, side, stop, tr):
        if rule in done:
            return
        r = trade(day, sym, bars, i, side, stop, tr, rule)
        if r:
            out.append(r)
            done.add(rule)

    for i in range(3, len(bars)):
        t, o, h, l, c = bars[i]
        if t > "14:45":
            break
        # 1. ORB long (the current Auto-Pilot rule): first close above the 15-min range, stop range low, 2R
        if c > o_hi:
            once("orb_long_2R", i, 1, o_lo, 2.0)
            if t <= "10:30":
                once("orb_long_early_2R", i, 1, o_lo, 2.0)
            once("orb_long_mid_1R", i, 1, o_mid, 1.0)
        # 2. ORB short: first close below the range, stop range high
        if c < o_lo:
            once("orb_short_2R", i, -1, o_hi, 2.0)
            once("orb_short_mid_1R", i, -1, o_mid, 1.0)
        # 3. VWAP reclaim after 10:00 in an up day: open above prev close, dip below VWAP, close back above
        if t >= "10:00" and prev and day_open > prev[2] and i > 0 and bars[i - 1][4] < vwap[i - 1] and c > vwap[i]:
            lo = min(b[3] for b in bars[max(0, i - 3):i + 1])
            once("vwap_reclaim_long_2R", i, 1, lo, 2.0)
        if t >= "10:00" and prev and day_open < prev[2] and i > 0 and bars[i - 1][4] > vwap[i - 1] and c < vwap[i]:
            hi = max(b[2] for b in bars[max(0, i - 3):i + 1])
            once("vwap_reject_short_2R", i, -1, hi, 2.0)
        # 4. Previous-day high breakout / low breakdown
        if prev and c > prev[0] and bars[i - 1][4] <= prev[0]:
            once("pdh_break_long_2R", i, 1, min(b[3] for b in bars[max(0, i - 3):i + 1]), 2.0)
        if prev and c < prev[1] and bars[i - 1][4] >= prev[1]:
            once("pdl_break_short_2R", i, -1, max(b[2] for b in bars[max(0, i - 3):i + 1]), 2.0)
    # 5. Gap fade: gap over 1 % from yesterday's close, fade at 09:30 toward the close, stop at the 15-min extreme
    if prev:
        gap = (day_open - prev[2]) / prev[2]
        if gap > 0.01:
            out.append(trade(day, sym, bars, 2, -1, o_hi * 1.0005, 1.5, "gap_up_fade_1.5R"))
        elif gap < -0.01:
            out.append(trade(day, sym, bars, 2, 1, o_lo * 0.9995, 1.5, "gap_down_fade_1.5R"))
    return [r for r in out if r]


def main():
    rows = []
    for k, sym in enumerate(NSE_UNIVERSE, 1):
        df = load(sym)
        if df.empty:
            print("no data for", sym)
            continue
        prev = None
        for day, d in df.groupby(df.index.date):
            d = d.between_time("09:15", "15:25")
            rows += day_rules(sym, day, d, prev)
            prev = (d["High"].max(), d["Low"].min(), d["Close"].iloc[-1]) if len(d) else prev
        print("\r%d/%d %s" % (k, len(NSE_UNIVERSE), sym), end="", flush=True)
    print()
    t = pd.DataFrame(rows)
    days = sorted(t["day"].unique())
    half = days[len(days) // 2]
    t["half"] = np.where(t["day"] < half, "A", "B")
    rng = np.random.default_rng(7)
    res = []
    for rule, g in t.groupby("rule"):
        a, b = g[g.half == "A"]["R_net"], g[g.half == "B"]["R_net"]
        boot = [rng.choice(g["R_net"].values, len(g)).mean() for _ in range(2000)]
        res.append({"rule": rule, "trades": len(g), "win%": round(100 * (g["net"] > 0).mean(), 1),
                    "avgR_gross": round(g["R_gross"].mean(), 3), "avgR_net": round(g["R_net"].mean(), 3),
                    "half_A": round(a.mean(), 3), "half_B": round(b.mean(), 3),
                    "ci5": round(np.percentile(boot, 5), 3), "net_rs": round(g["net"].sum()),
                    "per_day": round(len(g) / len(days), 1)})
    r = pd.DataFrame(res).sort_values("avgR_net", ascending=False)
    pd.set_option("display.width", 200)
    print("%d trading days (%s to %s), halves split at %s, Rs %d risk a trade, after Zerodha charges"
          % (len(days), days[0], days[-1], half, RISK))
    print(r.to_string(index=False))
    t.to_csv(os.path.join(CACHE, "trades.csv"), index=False)
    r.to_csv(os.path.join(CACHE, "summary.csv"), index=False)
    ok = r[(r.half_A > 0) & (r.half_B > 0) & (r.ci5 > 0) & (r.trades >= 60)]
    print("\nPasses (net > 0 in both halves, 5th-percentile bootstrap > 0, 60+ trades):",
          ", ".join(ok.rule) if len(ok) else "none")


if __name__ == "__main__":
    main()
