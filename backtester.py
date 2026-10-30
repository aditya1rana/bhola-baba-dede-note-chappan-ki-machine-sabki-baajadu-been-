"""
Strategy Backtester for Indian Equities
Capital-constrained portfolio simulation (Rs. 1 lakh, 1% risk per trade, real cash limits)
with NSE delivery costs (STT, fees, stamp duty, GST), brokerage, slippage and gap-aware fills.

Compares the original breakout strategy, the pullback swing strategy and the monthly momentum
rotation against buy-and-hold benchmarks, separately for the tuning period (before
BACKTEST_SPLIT_DATE) and the untouched validation period (after it).
"""

import sys
import pandas as pd
import numpy as np
from config import (
    BACKTEST_UNIVERSE, BACKTEST_PERIOD, BACKTEST_SPLIT_DATE, INITIAL_CAPITAL, RISK_PER_TRADE_PCT,
    BROKERAGE_PER_ORDER, SLIPPAGE_PCT, STATUTORY_COST_PCT, MOMENTUM_TOP_N,
    PULLBACK_STOP_ATR, PULLBACK_TARGET_R, PULLBACK_MAX_POSITION_PCT, CASH_YIELD_PCT, MOMENTUM_BUFFER_N,
)
from factors import BENCHMARK_TICKER, download_daily, compute_indicators, pullback_signals
from momentum import momentum_picks
from setups import SETUPS, swing_signals

WARMUP_BARS = 252  # 200 EMA and 12-month momentum both need a year of history


def _is_complete(df: pd.DataFrame, bench: pd.DataFrame) -> bool:
    """Yahoo occasionally returns a truncated history under rate limiting without raising.
    Treat a series as complete when it reaches the benchmark's last session and covers
    at least 97% of the benchmark's sessions since its own first bar."""
    if df.empty or df.index[-1] < bench.index[-1] - pd.Timedelta(days=5):
        return False
    expected = (bench.index >= df.index[0]).sum()
    return df.index.isin(bench.index).sum() >= 0.97 * expected


def load_universe(universe, period):
    bench = download_daily(BENCHMARK_TICKER, period)
    inds = {}
    incomplete = []
    for ticker in universe:
        sym = ticker.replace(".NS", "")
        df = download_daily(ticker, period)
        if not _is_complete(df, bench):
            df = download_daily(ticker, period)  # one retry
        if df.empty or len(df) < WARMUP_BARS + 50:
            print(f"  {sym:<12} skipped (insufficient data)")
            continue
        if not _is_complete(df, bench):
            incomplete.append(sym)
        inds[sym] = compute_indicators(df, bench).reindex(bench.index)
    if incomplete:
        print(f"  WARNING: incomplete price history for {', '.join(incomplete)}; "
              f"results may be off. Re-run in a few minutes.")
    return bench, inds


def _frame(inds, col):
    return pd.DataFrame({s: ind[col] for s, ind in inds.items()})


def simulate_swing(bench, inds, signals: dict, start, end, stop_atr=2.0, target_r=2.5,
                   breakeven_r=None, fill="close", capital=INITIAL_CAPITAL, cash_yield=CASH_YIELD_PCT):
    """Daily portfolio loop. Signals rank by 3-month relative strength when cash is limited.
    fill='close' assumes the order is placed in the last minutes before the close (3:20-3:30 PM);
    fill='open' buys at the next session's open."""
    syms = list(inds)
    idx = bench.index
    O, H, L, C, ATR = (_frame(inds, k).values for k in ("Open", "High", "Low", "Close", "atr"))
    RS = (_frame(inds, "ret_63") - _frame(inds, "bench_ret_63")).values
    SIG = np.column_stack([signals[s].reindex(idx).fillna(False).values for s in syms])
    cost_side = STATUTORY_COST_PCT + SLIPPAGE_PCT
    i0 = max(WARMUP_BARS, idx.searchsorted(pd.Timestamp(start)))
    i1 = idx.searchsorted(pd.Timestamp(end))

    daily_yield = (1 + cash_yield) ** (1 / 252) - 1
    cash, positions, trades, equity_curve = capital, {}, [], []
    for i in range(i0, i1):
        cash *= 1 + daily_yield  # idle cash parked in a liquid fund
        for j in list(positions):
            p = positions[j]
            o, h, l, c = O[i, j], H[i, j], L[i, j], C[i, j]
            if np.isnan(c):
                continue
            exit_px = None
            if o <= p["stop"]:
                exit_px = o
            elif l <= p["stop"]:
                exit_px = p["stop"]
            elif o >= p["target"]:
                exit_px = o
            elif h >= p["target"]:
                exit_px = p["target"]
            if exit_px is not None:
                proceeds = exit_px * p["shares"] * (1 - cost_side) - BROKERAGE_PER_ORDER
                cash += proceeds
                trades.append((proceeds - p["cost"]) / p["risk"])
                del positions[j]
            elif breakeven_r and h >= p["entry"] + breakeven_r * p["r1"]:
                p["stop"] = max(p["stop"], p["entry"] * (1 + 2 * cost_side + 0.002))

        equity = cash + sum(p["shares"] * C[i, j] for j, p in positions.items() if not np.isnan(C[i, j]))
        equity_curve.append(equity)

        k = i if fill == "close" else i - 1
        candidates = [j for j in np.where(SIG[k])[0] if j not in positions and not np.isnan(ATR[k, j])]
        candidates.sort(key=lambda j: -np.nan_to_num(RS[k, j]))
        for j in candidates:
            px = C[i, j] if fill == "close" else O[i, j]
            if np.isnan(px):
                continue
            px *= (1 + SLIPPAGE_PCT)
            r1 = stop_atr * ATR[k, j]
            shares = int(min(equity * RISK_PER_TRADE_PCT / r1, equity * PULLBACK_MAX_POSITION_PCT / px))
            cost = shares * px * (1 + STATUTORY_COST_PCT) + BROKERAGE_PER_ORDER
            if shares < 1 or cost > cash:
                continue
            cash -= cost
            positions[j] = {"entry": px, "stop": px - r1, "target": px + target_r * r1, "r1": r1,
                            "shares": shares, "cost": cost, "risk": shares * r1}
    return pd.Series(equity_curve, index=idx[i0:i1]), trades


def simulate_momentum(bench, inds, start, end, top_n=MOMENTUM_TOP_N, capital=INITIAL_CAPITAL,
                      cash_yield=CASH_YIELD_PCT, buffer_n=MOMENTUM_BUFFER_N, inverse_vol=False):
    """Monthly rebalance: decide on the last close of the month, trade at the next open.
    inverse_vol sizes new buys by 1/(63-day volatility) instead of equal weight. It was tested and
    rejected (lower Sharpe in both periods), so it stays off by default."""
    closes, opens = _frame(inds, "Close").ffill(), _frame(inds, "Open").ffill()
    idx = bench.index
    i0 = max(WARMUP_BARS, idx.searchsorted(pd.Timestamp(start)))
    i1 = idx.searchsorted(pd.Timestamp(end))
    cost_side = STATUTORY_COST_PCT + SLIPPAGE_PCT

    vol = closes.pct_change().rolling(63).std()
    daily_yield = (1 + cash_yield) ** (1 / 252) - 1
    cash, holdings, trades, equity_curve = capital, {}, [], []
    for i in range(i0, i1):
        cash *= 1 + daily_yield
        if idx[i].month != idx[i - 1].month:
            picks = momentum_picks(closes, bench["Close"], i - 1, top_n, held=list(holdings), buffer_n=buffer_n)
            for s in list(holdings):
                if s not in picks:
                    shares, cost = holdings.pop(s)
                    proceeds = shares * opens[s].iloc[i] * (1 - cost_side) - BROKERAGE_PER_ORDER
                    cash += proceeds
                    trades.append(proceeds / cost - 1)
            equity = cash + sum(sh * opens[s].iloc[i] for s, (sh, _) in holdings.items())
            if inverse_vol and picks:
                inv = 1 / vol[picks].iloc[i - 1]
                weights = (inv / inv.sum() * len(picks) / top_n).to_dict()
            else:
                weights = {s: 1 / top_n for s in picks}
            for s in picks:
                if s in holdings:
                    continue
                px = opens[s].iloc[i] * (1 + cost_side)
                shares = int(min(cash, equity * weights[s]) / px)
                if shares > 0:
                    cost = shares * px + BROKERAGE_PER_ORDER
                    cash -= cost
                    holdings[s] = (shares, cost)
        equity_curve.append(cash + sum(sh * closes[s].iloc[i] for s, (sh, _) in holdings.items()))
    return pd.Series(equity_curve, index=idx[i0:i1]), trades


def _blend(a, b):
    return a[0] + b[0], a[1] + b[1]


def buy_and_hold(series: pd.Series, start, end) -> pd.Series:
    s = series.loc[start:end].dropna()
    return s / s.iloc[0] * INITIAL_CAPITAL


def summarize(equity: pd.Series, trades: list) -> dict:
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    daily = equity.pct_change().dropna()
    t = np.array(trades)
    return {
        "cagr": ((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100,
        "max_dd": (1 - equity / equity.cummax()).max() * 100,
        "sharpe": daily.mean() / daily.std() * np.sqrt(252) if daily.std() else 0.0,
        "trades": len(t),
        "win_rate": (t > 0).mean() * 100 if len(t) else float("nan"),
    }


def run_portfolio_backtest(universe=None, period: str = None):
    universe = universe or BACKTEST_UNIVERSE
    period = period or BACKTEST_PERIOD

    print("\n" + "=" * 96)
    print(f"   NSE STRATEGY COMPARISON ({period}, {len(universe)} stocks) - realistic portfolio simulation")
    print("=" * 96)
    print(f"Rs. {INITIAL_CAPITAL:,.0f} capital | {RISK_PER_TRADE_PCT*100:.0f}% risk per swing trade | "
          f"Costs/side: {STATUTORY_COST_PCT*100:.2f}% STT+fees, {SLIPPAGE_PCT*100:.2f}% slippage, Rs. {BROKERAGE_PER_ORDER:.0f} brokerage")
    print(f"Idle cash earns {CASH_YIELD_PCT*100:.1f}%/yr (liquid ETF) in every strategy. Taxes are NOT modelled.")
    print("Downloading data...")
    bench, inds = load_universe(universe, period)

    breakout = {s: (ind["Close"] > ind["high_20"]) & (ind["ema20"] > ind["ema50"]) for s, ind in inds.items()}
    pullback_v1 = {s: (ind["ema20"] > ind["ema50"]) & (ind["ema50"] > ind["ema200"]) & (ind["Low"] <= ind["ema20"])
                   & (ind["Close"] > ind["ema20"]) & (ind["Close"] > ind["Open"]) & ind["rsi"].between(40, 60)
                   for s, ind in inds.items()}
    pullback_tuned = {s: pullback_signals(ind) for s, ind in inds.items()}
    swing = {s: swing_signals(ind) for s, ind in inds.items()}
    equal_weight = (_frame(inds, "Close").pct_change().mean(axis=1).fillna(0) + 1).cumprod()

    first = bench.index[WARMUP_BARS].strftime("%Y-%m-%d")
    last = (bench.index[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    periods = {
        f"TUNING {first[:4]}-{BACKTEST_SPLIT_DATE[:4]}": (first, BACKTEST_SPLIT_DATE),
        f"VALIDATION {BACKTEST_SPLIT_DATE[:4]}-{last[:4]} (unseen)": (BACKTEST_SPLIT_DATE, last),
        f"FULL {first[:4]}-{last[:4]}": (first, last),
    }
    strategies = {
        "Old breakout": lambda a, z: simulate_swing(bench, inds, breakout, a, z, 2.0, 2.5),
        "Pullback v1 (prev.)": lambda a, z: simulate_swing(bench, inds, pullback_v1, a, z, 2.0, 2.5, breakeven_r=1.0),
        "Pullback tuned": lambda a, z: simulate_swing(bench, inds, pullback_tuned, a, z, PULLBACK_STOP_ATR, PULLBACK_TARGET_R),
        "SWING pullback|pin bar": lambda a, z: simulate_swing(bench, inds, swing, a, z, PULLBACK_STOP_ATR, PULLBACK_TARGET_R),
        "  same, next-open fill": lambda a, z: simulate_swing(bench, inds, swing, a, z, PULLBACK_STOP_ATR, PULLBACK_TARGET_R, fill="open"),
        f"MOMENTUM top-{MOMENTUM_TOP_N} (buf {MOMENTUM_BUFFER_N})": lambda a, z: simulate_momentum(bench, inds, a, z),
        "  50/50 mom + swing": lambda a, z: _blend(simulate_momentum(bench, inds, a, z, capital=INITIAL_CAPITAL / 2),
                                                   simulate_swing(bench, inds, swing, a, z, PULLBACK_STOP_ATR,
                                                                  PULLBACK_TARGET_R, capital=INITIAL_CAPITAL / 2)),
        "NIFTY buy & hold": lambda a, z: (buy_and_hold(bench["Close"], a, z), []),
        "Equal-wt universe B&H": lambda a, z: (buy_and_hold(equal_weight, a, z), []),
    }

    for label, (a, z) in periods.items():
        print(f"\n--- {label} " + "-" * (92 - len(label)))
        print(f"{'Strategy':<24} | {'CAGR':>7} | {'Max DD':>7} | {'Sharpe':>6} | {'Trades':>6} | {'Win %':>6} | {'Final Rs.':>12}")
        for name, fn in strategies.items():
            eq, trades = fn(a, z)
            s = summarize(eq, trades)
            win = f"{s['win_rate']:5.1f}%" if s["trades"] else "    - "
            print(f"{name:<24} | {s['cagr']:>6.1f}% | {s['max_dd']:>6.1f}% | {s['sharpe']:>6.2f} | {s['trades']:>6} | {win} | {eq.iloc[-1]:>12,.0f}")

    print("\n" + "=" * 96)
    print("How to read this:")
    print(" * Parameters were chosen using only the TUNING period; VALIDATION is the honest estimate.")
    print(" * The universe is today's large caps (survivorship bias), so all numbers are optimistic;")
    print("   compare strategies against 'Equal-wt universe B&H', not just NIFTY.")
    print(" * Past results do not guarantee future returns.")
    print("=" * 96)


def run_setup_comparison(universe=None, period: str = None):
    """Every candidate swing setup with identical exits and costs, alone and added to the pullback."""
    universe = universe or BACKTEST_UNIVERSE
    period = period or BACKTEST_PERIOD
    print("\n" + "=" * 96)
    print(f"   SWING SETUP COMPARISON ({period}, {len(universe)} stocks): {PULLBACK_STOP_ATR:g} ATR stop, "
          f"{PULLBACK_TARGET_R:g}R target, market filter on")
    print("=" * 96)
    print("Downloading data...")
    bench, inds = load_universe(universe, period)
    first = bench.index[WARMUP_BARS].strftime("%Y-%m-%d")
    last = (bench.index[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    periods = [(first, BACKTEST_SPLIT_DATE), (BACKTEST_SPLIT_DATE, last)]
    pullback = {s: pullback_signals(ind) for s, ind in inds.items()}
    rows = {"Pullback (20 EMA)": pullback}
    for name, fn in SETUPS.items():
        sig = {s: fn(ind) & ind["bench_above_ema50"].astype(bool) for s, ind in inds.items()}
        rows[name] = sig
        rows[f"  pullback OR {name}"] = {s: pullback[s] | sig[s] for s in inds}

    print(f"\n{'Setup':<38} | TUNING {first[:4]}-{BACKTEST_SPLIT_DATE[:4]}: CAGR  Sharpe | "
          f"VALIDATION {BACKTEST_SPLIT_DATE[:4]}-{last[:4]}: CAGR  Sharpe | Verdict")
    print("-" * 110)
    base = None
    for name, sig in rows.items():
        res = [summarize(*simulate_swing(bench, inds, sig, a, z, PULLBACK_STOP_ATR, PULLBACK_TARGET_R)) for a, z in periods]
        if base is None:
            base, verdict = res, "baseline"
        else:
            better = all(r["sharpe"] > b["sharpe"] for r, b in zip(res, base))
            verdict = "ADOPT (better in both)" if better else "reject"
        print(f"{name:<38} | {res[0]['cagr']:>17.1f}% {res[0]['sharpe']:>7.2f} | "
              f"{res[1]['cagr']:>21.1f}% {res[1]['sharpe']:>7.2f} | {verdict}")
    print("-" * 110)
    print("A setup is adopted only if it raises Sharpe in BOTH periods versus the pullback baseline.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setups":
        run_setup_comparison()
    else:
        run_portfolio_backtest(period=sys.argv[1] if len(sys.argv) > 1 else None)
