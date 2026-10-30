"""
Market Screener & Setup Finder for NSE Stocks
Shows the monthly Momentum Rotation portfolio, flags Pullback and Pin-Bar swing entries,
scores multi-factor confluence, and sizes positions with the backtested rules.
"""

import pandas as pd
from config import (
    WATCHLIST, BACKTEST_UNIVERSE, INITIAL_CAPITAL, RISK_PER_TRADE_PCT,
    PULLBACK_STOP_ATR, PULLBACK_TARGET_R, MOMENTUM_TOP_N, MOMENTUM_BUFFER_N,
)
from factors import (
    BENCHMARK_TICKER, FACTOR_WEIGHTS, download_daily, compute_indicators, latest_factor_report,
)
from momentum import momentum_report
from setups import pin_bar_rejection


def analyze_stock(ticker: str, bench: pd.DataFrame = None) -> dict:
    """Fetch daily data and perform technical, multi-factor & risk evaluation."""
    clean_sym = ticker.replace(".NS", "")
    try:
        df = download_daily(ticker, period="2y")
        if df.empty or len(df) < 220:
            return {"symbol": clean_sym, "status": "Insufficient Data"}

        ind = compute_indicators(df, bench)
        last = ind.iloc[-1]
        ltp = float(last["Close"])
        change_pct = (ltp / float(ind["Close"].iloc[-2]) - 1) * 100

        if last["ema20"] > last["ema50"] > last["ema200"]:
            trend = "STRONG UPTREND"
        elif last["ema20"] < last["ema50"] < last["ema200"]:
            trend = "DOWNTREND"
        else:
            trend = "NEUTRAL / SIDEWAYS"

        report = latest_factor_report(ind)

        # Position Sizing: Risk 1% of Capital (Default ₹1,000), stop at PULLBACK_STOP_ATR x ATR
        risk_budget = INITIAL_CAPITAL * RISK_PER_TRADE_PCT
        risk_per_share = max(0.01, PULLBACK_STOP_ATR * float(last["atr"]))
        sl_price = round(ltp - risk_per_share, 2)
        return {
            "symbol": clean_sym,
            "ltp": round(ltp, 2),
            "change_pct": round(change_pct, 2),
            "trend": trend,
            "rsi": round(float(last["rsi"]), 1),
            "score": report["score"],
            "is_pullback": report["pullback_signal"],
            "is_pin_bar": bool(pin_bar_rejection(ind).iloc[-1] and last["bench_above_ema50"]),
            "high_conviction": report["high_conviction"],
            "failed_factors": report["failed"],
            "suggested_sl": sl_price,
            "market_ok": bool(last["bench_above_ema50"]),
            "suggested_target": round(ltp + PULLBACK_TARGET_R * risk_per_share, 2),
            "suggested_qty": max(1, int(risk_budget / risk_per_share)),
            "status": "OK"
        }
    except Exception as e:
        return {"symbol": clean_sym, "status": f"Error: {str(e)}"}


def scan_watchlist():
    """Scan all stocks in watchlist and print a formatted summary."""
    print("\n" + "=" * 84)
    print("      INDIAN MARKET SCANNER & TRADE OPPORTUNITY FINDER (NSE)")
    print("=" * 84)
    print(f"{'Stock':<12} | {'LTP (Rs.)':<10} | {'Change %':<9} | {'RSI':<5} | {'Trend':<18} | {'Score':<5} | {'Setup'}")
    print("-" * 84)

    bench = download_daily(BENCHMARK_TICKER, period="2y")
    market_ok = None
    candidates = []
    for ticker in WATCHLIST:
        res = analyze_stock(ticker, bench)
        if res.get("status") == "OK":
            market_ok = res["market_ok"]
            setup = "PULLBACK BUY" if res["is_pullback"] else ("PIN BAR BUY" if res["is_pin_bar"] else "None")
            print(f"{res['symbol']:<12} | {res['ltp']:<10.2f} | {res['change_pct']:<+8.2f}% | {res['rsi']:<5.1f} | "
                  f"{res['trend']:<18} | {res['score']:<5.0f} | {setup}")
            if res["is_pullback"] or res["is_pin_bar"]:
                candidates.append(res)
        else:
            print(f"{res['symbol']:<12} | {res['status']}")

    print("=" * 84)
    print(f"Score = weighted confluence of {len(FACTOR_WEIGHTS)} factors (0-100), shown for context.")
    if market_ok is False:
        print("Market regime: NIFTY is below its rising 50 EMA -> swing entries are switched off.")
    if candidates:
        print("\n[Trade Planning & Risk Allocation for Swing Setups (pullback / pin bar)]")
        for c in candidates:
            print(f"\n* Stock: {c['symbol']} (LTP: Rs. {c['ltp']}) | Confluence {c['score']:.0f}/100"
                  f"{' (HIGH CONVICTION)' if c['high_conviction'] else ''}")
            print(f"  - Recommended Entry: Rs. {c['ltp']}")
            print("  - Entry timing: place the order near the close (3:20-3:30 PM) once the setup holds")
            print(f"  - Stop Loss ({PULLBACK_STOP_ATR:g} ATR): Rs. {c['suggested_sl']} (Risk: Rs. {round(c['ltp'] - c['suggested_sl'], 2)}/share)")
            print(f"  - Target ({PULLBACK_TARGET_R:g}R):     Rs. {c['suggested_target']} (no breakeven move: it lowered returns after costs)")
            print(f"  - Safe Position Size: {c['suggested_qty']} shares (Max Risk: Rs. {INITIAL_CAPITAL * RISK_PER_TRADE_PCT:.0f})")
            if c["failed_factors"]:
                print(f"  - Weak factors: {', '.join(c['failed_factors'])}")
    else:
        print("\nNo pullback or pin-bar setups active right now. Capital safely preserved.")


def show_momentum_portfolio():
    """Print this month's Momentum Rotation target portfolio (rebalance on the first trading day)."""
    print("\n" + "=" * 84)
    print(f"      MOMENTUM ROTATION - TARGET PORTFOLIO (top {MOMENTUM_TOP_N} of {len(BACKTEST_UNIVERSE)} large caps)")
    print("=" * 84)
    bench = download_daily(BENCHMARK_TICKER, period="2y")
    closes = pd.DataFrame({t.replace(".NS", ""): download_daily(t, period="2y")["Close"]
                           for t in BACKTEST_UNIVERSE}).reindex(bench.index).ffill()
    rep = momentum_report(closes, bench["Close"])
    print(f"As of {rep['as_of']} | NIFTY {rep['nifty']:,.0f} vs 200-day avg {rep['nifty_sma']:,.0f} -> "
          f"{'RISK ON' if rep['risk_on'] else 'RISK OFF (hold cash)'}")
    if not rep["picks"]:
        print("\nNo holdings: keep capital in a liquid ETF (e.g. LIQUIDBEES) until the next monthly rebalance.")
        return
    alloc = INITIAL_CAPITAL / MOMENTUM_TOP_N
    print(f"\n{'#':<3} {'Stock':<12} | {'12-1M Return':>12} | {'Price (Rs.)':>11} | {'Shares for Rs. ' + format(alloc, ',.0f'):>20} | Action")
    print("-" * 96)
    for n, (sym, score, price) in enumerate(rep["picks"], 1):
        action = "BUY / HOLD" if n <= MOMENTUM_TOP_N else "HOLD only if already owned"
        print(f"{n:<3} {sym:<12} | {score*100:>+11.1f}% | {price:>11,.2f} | {int(alloc // price):>20} | {action}")
    print("-" * 96)
    print(f"Rebalance on the first trading day of each month: sell holdings ranked below #{MOMENTUM_BUFFER_N},")
    print(f"then fill empty slots (up to {MOMENTUM_TOP_N}) from the top of the list. Park idle cash in a liquid ETF.")


if __name__ == "__main__":
    scan_watchlist()
    show_momentum_portfolio()
