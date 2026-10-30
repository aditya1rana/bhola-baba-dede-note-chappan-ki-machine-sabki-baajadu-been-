"""
Opening-Range Breakout (ORB) Test on NSE 5-minute bars
Ported from the trader-entry / trader-exit / trader-timemachine skills (US market) to NSE hours:
15-minute opening range (9:15-9:30 IST), entry on the first 5-minute CLOSE above the range high
between 9:30 and 14:30, stop at the range midpoint or low, target 1R or 2R, flat by 15:20.
The stop is checked before the target inside a bar. Yahoo only keeps 60 days of 5-minute bars,
so this is a short sample; the bootstrap range shows how uncertain the average is.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from config import BACKTEST_UNIVERSE

INTRADAY_COST_SIDE = 0.0002 + 0.0003  # STT 0.025% on the sell, fees, stamp, GST + slippage, per side
BROKERAGE = 20.0
RISK_PER_TRADE = 1000.0


def download_5m(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, period="60d", interval="5m", progress=False, auto_adjust=True)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_convert("Asia/Kolkata")
    return df


def _after_market_or(nifty: pd.DataFrame) -> dict:
    """(day, bar time) -> True when NIFTY trades above its own opening-range high."""
    ok = {}
    for day, s in nifty.groupby(nifty.index.date):
        orng = s.between_time("09:15", "09:25")
        if len(orng) < 3:
            continue
        hi = orng["High"].max()
        for t, c in s["Close"].items():
            ok[(day, t)] = c > hi
    return ok


def orb_trades(df: pd.DataFrame, stop_rule="or-mid", target_r=1.0, market_ok: dict = None) -> list:
    """R multiple (after costs) of each ORB trade, one per session at most."""
    last_entry, flat_after = pd.Timestamp("14:30").time(), pd.Timestamp("15:15").time()
    out = []
    for day, s in df.groupby(df.index.date):
        s = s.between_time("09:15", "15:25")
        if len(s) < 70:  # full sessions only
            continue
        orng = s.between_time("09:15", "09:25")
        if len(orng) < 3:
            continue
        hi, lo = orng["High"].max(), orng["Low"].min()
        stop = (hi + lo) / 2 if stop_rule == "or-mid" else lo
        after = s.between_time("09:30", "15:25")
        trig = after[(after["Close"] > hi) & (after.index.time <= last_entry)]
        if trig.empty:
            continue
        t0 = trig.index[0]
        if market_ok is not None and not market_ok.get((day, t0), False):
            continue
        entry = trig["Close"].iloc[0]
        risk = entry - stop
        if risk <= entry * 0.0005:  # too tight to survive the spread
            continue
        target = entry + target_r * risk
        exit_px = after["Close"].iloc[-1]
        for t, b in after[after.index > t0].iterrows():
            if t.time() > flat_after:
                exit_px = b["Open"]
                break
            if b["Low"] <= stop:
                exit_px = min(stop, b["Open"])
                break
            if b["High"] >= target:
                exit_px = max(target, b["Open"])
                break
        shares = RISK_PER_TRADE / risk
        pnl = (exit_px - entry) * shares - shares * (entry + exit_px) * INTRADAY_COST_SIDE - 2 * BROKERAGE
        out.append(pnl / RISK_PER_TRADE)
    return out


def run_orb_test(universe=None):
    universe = universe or BACKTEST_UNIVERSE
    print("\n" + "=" * 84)
    print(f"   OPENING-RANGE BREAKOUT on NSE 5-min bars ({len(universe)} stocks, last 60 days)")
    print("=" * 84)
    print("Downloading 5-minute bars...")
    bars = {t: df for t in universe if not (df := download_5m(t)).empty}
    nifty = download_5m("^NSEI")
    market_ok = _after_market_or(nifty) if not nifty.empty else None
    rng = np.random.default_rng(19)

    print(f"{'Variant':<34}| {'Trades':>6} | {'Win %':>5} | {'Avg R':>6} | 95% range of avg R (bootstrap, seed 19)")
    print("-" * 84)
    for filt in (None, market_ok):
        for stop_rule in ("or-mid", "or-low"):
            for target_r in (1.0, 2.0):
                r = np.array([x for df in bars.values() for x in orb_trades(df, stop_rule, target_r, filt)])
                if not len(r):
                    continue
                lo, hi = np.percentile([rng.choice(r, len(r)).mean() for _ in range(2000)], [2.5, 97.5])
                name = f"stop {stop_rule}, {target_r:.0f}R" + (" + NIFTY > its OR" if filt else "")
                print(f"{name:<34}| {len(r):>6} | {(r > 0).mean()*100:4.1f}% | {r.mean():+6.3f} | [{lo:+.3f}, {hi:+.3f}]")
    print("-" * 84)
    print("Avg R is profit per trade in units of the amount risked, after intraday costs.")
    print("A range entirely below zero means the setup lost money in this sample, not bad luck.")


if __name__ == "__main__":
    run_orb_test()
