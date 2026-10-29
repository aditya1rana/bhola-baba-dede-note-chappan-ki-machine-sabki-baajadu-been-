"""
Strategy Backtester for Indian Equities
Backtests Trend & Breakout Strategy with Stop-Loss, 1:2 Target, and Brokerage Friction.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from config import WATCHLIST, INITIAL_CAPITAL, RISK_PER_TRADE_PCT, BROKERAGE_PER_ORDER


def backtest_symbol(ticker: str, period: str = "1y") -> dict:
    clean_sym = ticker.replace(".NS", "")
    df = yf.download(ticker, period=period, interval="1d", progress=False)
    if df.empty or len(df) < 50:
        return {"symbol": clean_sym, "trades": 0}

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.copy()
    close = df['Close']
    high = df['High']
    low = df['Low']

    ema_20 = close.ewm(span=20, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()

    # 20-day high breakout
    high_20 = high.shift(1).rolling(20).max()

    # Calculate ATR (14)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    atr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

    in_position = False
    entry_price = 0.0
    stop_loss = 0.0
    target = 0.0
    shares = 0

    trades = []

    for i in range(50, len(df)):
        cur_close = float(close.iloc[i])
        cur_high = float(high.iloc[i])
        cur_low = float(low.iloc[i])
        cur_atr = float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else 10.0

        if in_position:
            # Check Stop-Loss
            if cur_low <= stop_loss:
                exit_price = stop_loss
                pnl = (exit_price - entry_price) * shares - (2 * BROKERAGE_PER_ORDER)
                trades.append({"symbol": clean_sym, "type": "SL", "pnl": pnl, "entry": entry_price, "exit": exit_price})
                in_position = False
            # Check Target
            elif cur_high >= target:
                exit_price = target
                pnl = (exit_price - entry_price) * shares - (2 * BROKERAGE_PER_ORDER)
                trades.append({"symbol": clean_sym, "type": "TARGET", "pnl": pnl, "entry": entry_price, "exit": exit_price})
                in_position = False

        if not in_position:
            # Trigger: 20-day high breakout with 20 EMA > 50 EMA
            if cur_close > high_20.iloc[i] and ema_20.iloc[i] > ema_50.iloc[i]:
                entry_price = cur_close
                # Use 2x ATR for Stop-Loss buffer
                stop_loss = entry_price - (2.0 * cur_atr)
                risk_per_share = max(1.0, entry_price - stop_loss)
                target = entry_price + (2.5 * risk_per_share)
                risk_budget = INITIAL_CAPITAL * RISK_PER_TRADE_PCT
                shares = max(1, int(risk_budget / risk_per_share))
                in_position = True

    return {
        "symbol": clean_sym,
        "trades": trades,
        "total_trades": len(trades),
        "wins": sum(1 for t in trades if t["pnl"] > 0),
        "losses": sum(1 for t in trades if t["pnl"] <= 0),
        "net_pnl": sum(t["pnl"] for t in trades)
    }


def run_portfolio_backtest():
    print("\n" + "=" * 70)
    print("      NSE PORTFOLIO BACKTEST REPORT (Past 1 Year - 1D Candles)")
    print("=" * 70)
    print(f"Initial Capital: Rs. {INITIAL_CAPITAL:,.2f} | Risk per Trade: {RISK_PER_TRADE_PCT*100}%")
    print(f"Brokerage per Trade: Rs. {BROKERAGE_PER_ORDER * 2} round-trip deducted")
    print("-" * 70)
    print(f"{'Stock':<12} | {'Trades':<8} | {'Win Rate':<10} | {'Wins / Losses':<15} | {'Net PnL (Rs.)'}")
    print("-" * 70)

    total_trades = 0
    total_wins = 0
    total_pnl = 0.0

    for ticker in WATCHLIST:
        res = backtest_symbol(ticker)
        t_count = res["total_trades"]
        if t_count > 0:
            win_rate = (res["wins"] / t_count) * 100
            total_trades += t_count
            total_wins += res["wins"]
            total_pnl += res["net_pnl"]
            print(f"{res['symbol']:<12} | {t_count:<8} | {win_rate:<9.1f}% | {res['wins']}W / {res['losses']}L{'':<8} | Rs. {res['net_pnl']:<+10.2f}")
        else:
            print(f"{res['symbol']:<12} | 0 trades")

    overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    print("=" * 70)
    print(f"Overall Total Trades: {total_trades}")
    print(f"Overall Win Rate:     {overall_win_rate:.1f}%")
    print(f"Total Net PnL:        Rs. {total_pnl:+,.2f}")
    print(f"Final Return:         {((total_pnl) / INITIAL_CAPITAL) * 100:+.2f}%")
    print("=" * 70)


if __name__ == "__main__":
    run_portfolio_backtest()
