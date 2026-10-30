"""
Momentum Rotation Strategy for NSE Equities
Once a month, hold the strongest stocks by 12-1 month return (equal weight), only if each
is above its own 200 EMA, and move fully to cash when NIFTY is below its 200-day average.
Existing holdings are kept while they still rank inside the top MOMENTUM_BUFFER_N.
"""

import pandas as pd
from config import (
    MOMENTUM_LOOKBACK_DAYS, MOMENTUM_SKIP_DAYS, MOMENTUM_TOP_N, MOMENTUM_REGIME_SMA, MOMENTUM_BUFFER_N,
)


def momentum_picks(closes: pd.DataFrame, bench_close: pd.Series, pos: int,
                   top_n: int = MOMENTUM_TOP_N, held=(), buffer_n: int = MOMENTUM_BUFFER_N) -> list:
    """Symbols to hold, decided with data up to and including row `pos`.
    With buffer_n, current holdings are kept while they still rank inside the top buffer_n."""
    if pos < MOMENTUM_LOOKBACK_DAYS:
        return []
    regime_sma = bench_close.rolling(MOMENTUM_REGIME_SMA).mean()
    if bench_close.iloc[pos] < regime_sma.iloc[pos]:
        return []
    score = closes.iloc[pos - MOMENTUM_SKIP_DAYS] / closes.iloc[pos - MOMENTUM_LOOKBACK_DAYS] - 1
    above_trend = closes.iloc[pos] > closes.ewm(span=200, adjust=False).mean().iloc[pos]
    ranked = list(score[score.notna() & above_trend & (score > 0)].sort_values(ascending=False).index)
    if not buffer_n:
        return ranked[:top_n]
    keep = [s for s in held if s in ranked[:buffer_n]][:top_n]
    return keep + [s for s in ranked if s not in keep][:top_n - len(keep)]


def momentum_report(closes: pd.DataFrame, bench_close: pd.Series) -> dict:
    """Current ranking: the top MOMENTUM_TOP_N are buys, ranks up to MOMENTUM_BUFFER_N are holds."""
    pos = len(closes) - 1
    picks = momentum_picks(closes, bench_close, pos, top_n=MOMENTUM_BUFFER_N, buffer_n=None)
    regime_sma = float(bench_close.rolling(MOMENTUM_REGIME_SMA).mean().iloc[pos])
    score = closes.iloc[pos - MOMENTUM_SKIP_DAYS] / closes.iloc[pos - MOMENTUM_LOOKBACK_DAYS] - 1
    return {
        "as_of": closes.index[pos].date(),
        "nifty": float(bench_close.iloc[pos]),
        "nifty_sma": regime_sma,
        "risk_on": bool(bench_close.iloc[pos] >= regime_sma),
        "picks": [(s, float(score[s]), float(closes[s].iloc[pos])) for s in picks],
    }
