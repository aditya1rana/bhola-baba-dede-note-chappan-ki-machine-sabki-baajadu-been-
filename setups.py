"""
Candidate Swing Setups for NSE Equities (daily candles)
Each function takes an indicator frame from factors.compute_indicators and returns a boolean
entry Series. Rules were fixed before backtesting; see backtester.py for the comparison.
"""

import pandas as pd

TEMA_RIBBON = (8, 13, 21, 34, 55)


def tema(close: pd.Series, span: int) -> pd.Series:
    """Triple EMA: 3*EMA1 - 3*EMA2 + EMA3 (less lag than a plain EMA)."""
    e1 = close.ewm(span=span, adjust=False).mean()
    e2 = e1.ewm(span=span, adjust=False).mean()
    e3 = e2.ewm(span=span, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3


def _uptrend(ind: pd.DataFrame) -> pd.Series:
    return (ind["Close"] > ind["ema200"]) & (ind["ema50"] > ind["ema200"])


def tema_ribbon_alignment(ind: pd.DataFrame) -> pd.Series:
    """The whole TEMA ribbon (8 > 13 > 21 > 34 > 55) turns fully bullish today, in an uptrend."""
    ribbon = [tema(ind["Close"], s) for s in TEMA_RIBBON]
    aligned = pd.concat([a > b for a, b in zip(ribbon, ribbon[1:])], axis=1).all(axis=1)
    return (aligned & ~aligned.shift(1, fill_value=False) & _uptrend(ind)).fillna(False)


def tema_slope_turn(ind: pd.DataFrame) -> pd.Series:
    """TEMA(21) slope turns from falling to rising while the price is above it, in an uptrend."""
    t = tema(ind["Close"], 21)
    turn = (t > t.shift(1)) & (t.shift(1) <= t.shift(2))
    return (turn & (ind["Close"] > t) & _uptrend(ind)).fillna(False)


def pin_bar_rejection(ind: pd.DataFrame) -> pd.Series:
    """Bullish pin bar: lower wick >= 2x body and >= 60% of the range, close in the top third,
    wick rejects the 50 EMA zone (low within 1% of it or below) and closes above it."""
    o, h, l, c = ind["Open"], ind["High"], ind["Low"], ind["Close"]
    rng = (h - l).where(h > l)
    body = (c - o).abs()
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l
    pin = (lower_wick >= 2 * body) & (lower_wick >= 0.6 * rng) & ((c - l) >= (2 / 3) * rng)
    at_level = (l <= ind["ema50"] * 1.01) & (c > ind["ema50"])
    return (pin & at_level & _uptrend(ind)).fillna(False)


def slow_ema_pullback(ind: pd.DataFrame) -> pd.Series:
    """Deeper pullback to the slow 50 EMA: tags it intraday, closes back above on a green candle,
    with the 50 EMA rising and above the 200 EMA."""
    rising = ind["ema50"] > ind["ema50"].shift(10)
    return ((ind["Low"] <= ind["ema50"]) & (ind["Close"] > ind["ema50"]) & (ind["Close"] > ind["Open"])
            & rising & (ind["ema50"] > ind["ema200"])).fillna(False)


def continuation_breakout(ind: pd.DataFrame) -> pd.Series:
    """Trend continuation: after a tight 5-day pause (range <= 2 ATR) inside a stacked uptrend,
    price closes above the pause's high."""
    pause_high = ind["High"].shift(1).rolling(5).max()
    pause_low = ind["Low"].shift(1).rolling(5).min()
    tight = (pause_high - pause_low) <= 2 * ind["atr"].shift(1)
    stacked = (ind["ema20"] > ind["ema50"]) & (ind["ema50"] > ind["ema200"])
    return (tight & stacked & (ind["Close"] > pause_high)).fillna(False)


SETUPS = {
    "TEMA ribbon alignment": tema_ribbon_alignment,
    "TEMA slope turn": tema_slope_turn,
    "Pin bar rejection": pin_bar_rejection,
    "Slow EMA pullback": slow_ema_pullback,
    "Continuation": continuation_breakout,
}


def swing_signals(ind: pd.DataFrame) -> pd.Series:
    """Adopted swing entry: 20 EMA pullback OR 50 EMA pin-bar rejection, both only while NIFTY is
    above its rising 50 EMA. The pin bar was the only candidate setup that improved Sharpe in both
    the tuning (2017-2021) and validation (2022-2026) periods; the others were rejected."""
    from factors import pullback_signals
    return pullback_signals(ind) | (pin_bar_rejection(ind) & ind["bench_above_ema50"].astype(bool))
