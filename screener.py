"""
Market Screener & Setup Finder for NSE Stocks
Identifies Trend, VCP Contraction, Breakout Setups, and Position Sizing.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from config import WATCHLIST, INITIAL_CAPITAL, RISK_PER_TRADE_PCT


def analyze_stock(ticker: str) -> dict:
    """Fetch daily data and perform technical & risk evaluation."""
    clean_sym = ticker.replace(".NS", "")
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if df.empty or len(df) < 50:
            return {"symbol": clean_sym, "status": "Insufficient Data"}

        # Flatten multi-level columns if returned by yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.copy()
        df['close'] = df['Close']
        df['high'] = df['High']
        df['low'] = df['Low']
        df['volume'] = df['Volume']

        ltp = float(df['close'].iloc[-1])
        prev_close = float(df['close'].iloc[-2])
        change_pct = ((ltp - prev_close) / prev_close) * 100

        # Moving Averages
        ema_20 = float(df['close'].ewm(span=20, adjust=False).mean().iloc[-1])
        ema_50 = float(df['close'].ewm(span=50, adjust=False).mean().iloc[-1])

        # RSI (14)
        delta = df['close'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        loss = (-1 * delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        # 20-day Range & Breakout Detection
        high_20d = float(df['high'].iloc[-21:-1].max())
        low_20d = float(df['low'].iloc[-21:-1].min())
        is_breakout = ltp > high_20d

        # Volatility Contraction Check (VCP hint: 5-day range is less than half of 20-day range)
        range_5d = float(df['high'].iloc[-5:].max() - df['low'].iloc[-5:].min())
        range_20d = high_20d - low_20d
        is_consolidating = (range_5d / range_20d) < 0.45 if range_20d > 0 else False

        # Trend Verdict
        if ltp > ema_20 > ema_50:
            trend = "STRONG UPTREND"
        elif ltp < ema_20 < ema_50:
            trend = "DOWNTREND"
        else:
            trend = "NEUTRAL / SIDEWAYS"

        # Position Sizing: Risk 1% of Capital (Default ₹1,000)
        risk_budget = INITIAL_CAPITAL * RISK_PER_TRADE_PCT
        sl_price = round(ema_20 if ltp > ema_20 else low_20d, 2)
        risk_per_share = max(1.0, ltp - sl_price)
        suggested_qty = max(1, int(risk_budget / risk_per_share))
        target_price = round(ltp + (2 * risk_per_share), 2)

        return {
            "symbol": clean_sym,
            "ltp": round(ltp, 2),
            "change_pct": round(change_pct, 2),
            "trend": trend,
            "rsi": round(rsi, 1),
            "is_breakout": is_breakout,
            "is_vcp": is_consolidating,
            "suggested_sl": sl_price,
            "suggested_target": target_price,
            "suggested_qty": suggested_qty,
            "status": "OK"
        }
    except Exception as e:
        return {"symbol": clean_sym, "status": f"Error: {str(e)}"}


def scan_watchlist():
    """Scan all stocks in watchlist and print a formatted summary."""
    print("\n" + "=" * 78)
    print("      INDIAN MARKET SCANNER & TRADE OPPORTUNITY FINDER (NSE)")
    print("=" * 78)
    print(f"{'Stock':<12} | {'LTP (Rs.)':<10} | {'Change %':<9} | {'RSI':<5} | {'Trend':<17} | {'Setup'}")
    print("-" * 78)

    candidates = []
    for ticker in WATCHLIST:
        res = analyze_stock(ticker)
        if res.get("status") == "OK":
            setup = "None"
            if res["is_breakout"]:
                setup = "BREAKOUT"
            elif res["is_vcp"]:
                setup = "VCP SQUEEZE"

            print(f"{res['symbol']:<12} | {res['ltp']:<10.2f} | {res['change_pct']:<+9.2f}% | {res['rsi']:<5.1f} | {res['trend']:<17} | {setup}")

            if res["is_breakout"] or res["is_vcp"] or res["trend"] == "STRONG UPTREND":
                candidates.append(res)
        else:
            print(f"{res['symbol']:<12} | Error fetching data")

    print("=" * 78)
    if candidates:
        print("\n[Trade Planning & Risk Allocation for Active Candidates]")
        for c in candidates:
            print(f"\n* Stock: {c['symbol']} (LTP: Rs. {c['ltp']})")
            print(f"  - Setup: {'Breakout' if c['is_breakout'] else ('VCP' if c['is_vcp'] else 'Trend Following')}")
            print(f"  - Recommended Entry: Rs. {c['ltp']}")
            print(f"  - Stop Loss: Rs. {c['suggested_sl']} (Risk: Rs. {round(c['ltp'] - c['suggested_sl'], 2)}/share)")
            print(f"  - Target (1:2 R:R): Rs. {c['suggested_target']}")
            print(f"  - Safe Position Size: {c['suggested_qty']} shares (Total Max Risk: Rs. {INITIAL_CAPITAL * RISK_PER_TRADE_PCT:.0f})")
    else:
        print("\nNo high-probability breakout setups active right now. Capital safely preserved.")


if __name__ == "__main__":
    scan_watchlist()
