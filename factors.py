"""
Multi-Factor Confluence Model for NSE Equities
Computes trend, momentum, strength, volume, volatility and market-regime factors
on daily candles and combines them into a single 0-100 confluence score.

Backtest findings (10y, 38 NSE large caps, tuned on 2017-2021, validated on 2022-2026):
- Stacking these factors as hard entry gates on 20-day breakouts did NOT help out of sample.
- Buying pullbacks to the 20 EMA inside an uptrend beat breakout entries.
- The market-regime factor was the only gate that helped consistently, so pullback_signals
  requires it. The remaining factors feed the informational score only.
"""

import pandas as pd
import numpy as np
import yfinance as yf

BENCHMARK_TICKER = "^NSEI"

# Factor weights (sum = 100) for the informational confluence score.
FACTOR_WEIGHTS = {
    "market_regime": 15,      # NIFTY above its 50 EMA and 50 EMA rising
    "trend_template": 15,     # Close > EMA50 > EMA200, EMA200 rising
    "relative_strength": 15,  # 3-month return beats NIFTY
    "adx_trend": 10,          # ADX(14) > 20 with +DI > -DI
    "macd_momentum": 10,      # MACD histogram positive and rising
    "rsi_zone": 10,           # RSI(14) between 55 and 75 (strong, not overbought)
    "volume_surge": 10,       # Volume >= 1.5x 50-day average
    "near_52w_high": 10,      # Within 15% of 52-week high
    "not_extended": 5,        # Close no more than 2.5 ATR above EMA20
}
HIGH_CONVICTION_SCORE = 75

# Pullback entry rule parameters
PULLBACK_RSI_RANGE = (35, 55)


def download_daily(ticker: str, period: str = "2y") -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"]).copy()


def compute_indicators(df: pd.DataFrame, bench: pd.DataFrame = None) -> pd.DataFrame:
    """Add all indicator columns to a daily OHLCV frame."""
    out = df.copy()
    close, high, low, vol = out["Close"], out["High"], out["Low"], out["Volume"]

    out["ema20"] = close.ewm(span=20, adjust=False).mean()
    out["ema50"] = close.ewm(span=50, adjust=False).mean()
    out["ema200"] = close.ewm(span=200, adjust=False).mean()

    # RSI (14, Wilder)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    out["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    # ATR (14, Wilder)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    out["atr"] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

    # ADX (14) with directional indicators
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=out.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=out.index)
    atr_s = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    out["plus_di"] = 100 * plus_dm.ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr_s
    out["minus_di"] = 100 * minus_dm.ewm(alpha=1/14, min_periods=14, adjust=False).mean() / atr_s
    dx = 100 * (out["plus_di"] - out["minus_di"]).abs() / (out["plus_di"] + out["minus_di"]).replace(0, np.nan)
    out["adx"] = dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

    # MACD (12, 26, 9)
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    out["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()

    out["vol_ratio"] = vol / vol.rolling(50).mean()
    out["high_20"] = high.shift(1).rolling(20).max()
    out["high_252"] = high.rolling(252, min_periods=120).max()
    out["ret_63"] = close.pct_change(63)

    if bench is not None and not bench.empty:
        b_close = bench["Close"].reindex(out.index).ffill()
        b_ema50 = b_close.ewm(span=50, adjust=False).mean()
        out["bench_above_ema50"] = (b_close > b_ema50) & (b_ema50 > b_ema50.shift(10))
        out["bench_ret_63"] = b_close.pct_change(63)
    else:
        out["bench_above_ema50"] = True
        out["bench_ret_63"] = 0.0

    return out


def factor_table(ind: pd.DataFrame) -> pd.DataFrame:
    """Boolean pass/fail for every factor on every bar."""
    f = pd.DataFrame(index=ind.index)
    f["market_regime"] = ind["bench_above_ema50"].astype(bool)
    f["trend_template"] = (ind["Close"] > ind["ema50"]) & (ind["ema50"] > ind["ema200"]) & (ind["ema200"] > ind["ema200"].shift(20))
    f["relative_strength"] = ind["ret_63"] > ind["bench_ret_63"]
    f["adx_trend"] = (ind["adx"] > 20) & (ind["plus_di"] > ind["minus_di"])
    f["macd_momentum"] = (ind["macd_hist"] > 0) & (ind["macd_hist"] > ind["macd_hist"].shift(1))
    f["rsi_zone"] = ind["rsi"].between(55, 75)
    f["volume_surge"] = ind["vol_ratio"] >= 1.5
    f["near_52w_high"] = ind["Close"] >= 0.85 * ind["high_252"]
    f["not_extended"] = (ind["Close"] - ind["ema20"]) <= 2.5 * ind["atr"]
    return f.fillna(False)


def confluence_score(factors: pd.DataFrame) -> pd.Series:
    score = sum(factors[name].astype(int) * w for name, w in FACTOR_WEIGHTS.items())
    return score.astype(float)


def pullback_signals(ind: pd.DataFrame) -> pd.Series:
    """Buy-the-dip in an uptrend during a healthy market: NIFTY above its rising 50 EMA,
    EMA20 > EMA50 > EMA200, price tags the 20 EMA intraday, closes back above it on a
    green candle, with RSI cooled off into the 35-55 zone."""
    lo, hi = PULLBACK_RSI_RANGE
    return (
        ind["bench_above_ema50"].astype(bool)
        & (ind["ema20"] > ind["ema50"]) & (ind["ema50"] > ind["ema200"])
        & (ind["Low"] <= ind["ema20"]) & (ind["Close"] > ind["ema20"])
        & (ind["Close"] > ind["Open"]) & ind["rsi"].between(lo, hi)
    ).fillna(False)


def latest_factor_report(ind: pd.DataFrame) -> dict:
    """Score breakdown and signal state for the most recent bar (used by the screener)."""
    factors = factor_table(ind)
    last = factors.iloc[-1]
    score = float(confluence_score(factors).iloc[-1])
    return {
        "score": round(score, 1),
        "pullback_signal": bool(pullback_signals(ind).iloc[-1]),
        "passed": [k for k in FACTOR_WEIGHTS if bool(last[k])],
        "failed": [k for k in FACTOR_WEIGHTS if not bool(last[k])],
        "high_conviction": score >= HIGH_CONVICTION_SCORE,
    }
