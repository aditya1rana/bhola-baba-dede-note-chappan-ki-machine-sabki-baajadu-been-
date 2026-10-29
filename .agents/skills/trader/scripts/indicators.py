"""
Vectorized Technical Indicators for Quantitative Strategies
Compatible with pandas DataFrame containing ['open', 'high', 'low', 'close', 'volume'].
"""

import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range (ATR)."""
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculate Intraday Volume Weighted Average Price (VWAP)."""
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    tp_volume = typical_price * df['volume']
    cumulative_tpv = tp_volume.cumsum()
    cumulative_vol = df['volume'].cumsum()
    return cumulative_tpv / cumulative_vol.replace(0, np.nan)


def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    """
    Calculate Supertrend indicator.
    Returns: (supertrend_series, direction_series: 1 for bullish, -1 for bearish)
    """
    atr = calculate_atr(df, period)
    hl2 = (df['high'] + df['low']) / 2
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    supertrend = [np.nan] * len(df)
    direction = [1] * len(df)

    close = df['close'].values
    upper = upper_band.values
    lower = lower_band.values

    for i in range(1, len(df)):
        if np.isnan(atr.iloc[i]):
            continue

        # Adjust bands
        if lower[i] < lower[i - 1] and close[i - 1] > lower[i - 1]:
            lower[i] = lower[i - 1]
        if upper[i] > upper[i - 1] and close[i - 1] < upper[i - 1]:
            upper[i] = upper[i - 1]

        # Determine direction
        if direction[i - 1] == 1:
            if close[i] < lower[i]:
                direction[i] = -1
                supertrend[i] = upper[i]
            else:
                direction[i] = 1
                supertrend[i] = lower[i]
        else:
            if close[i] > upper[i]:
                direction[i] = 1
                supertrend[i] = lower[i]
            else:
                direction[i] = -1
                supertrend[i] = upper[i]

    return pd.Series(supertrend, index=df.index), pd.Series(direction, index=df.index)


def calculate_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0):
    """Calculate Bollinger Bands (middle, upper, lower)."""
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + (std * num_std)
    lower = sma - (std * num_std)
    return sma, upper, lower
