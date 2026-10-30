"""
Configuration for Indian Market Trading Agent
"""

import os

# --- Trading Mode ---
# Options: 'PAPER' (Simulated execution) or 'LIVE' (Real Broker)
TRADING_MODE = "PAPER"

# --- Account & Risk Limits (In Indian Rupees - INR) ---
INITIAL_CAPITAL = 100000.0        # ₹1 Lakh starting virtual capital
MAX_DAILY_LOSS_PCT = 0.02         # 2% Circuit Breaker (halts bot if daily loss >= ₹2,000)
RISK_PER_TRADE_PCT = 0.01         # 1% Max risk per trade (₹1,000 risk per trade)
BROKERAGE_PER_ORDER = 20.0        # Flat ₹20 per trade (Zerodha/Angel One/Dhan standard)
SLIPPAGE_PCT = 0.0005             # 0.05% realistic execution slippage

# --- Target Stock Watchlist (NSE Symbols for yfinance) ---
WATCHLIST = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "ITC.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS"
]

# --- Broker Credentials (Optional - For Live Mode later) ---
BROKER_NAME = os.getenv("BROKER_NAME", "PAPER") # 'ANGEL_ONE', 'DHAN', 'ZERODHA'
BROKER_API_KEY = os.getenv("BROKER_API_KEY", "")
BROKER_CLIENT_ID = os.getenv("BROKER_CLIENT_ID", "")
BROKER_PIN = os.getenv("BROKER_PIN", "")
BROKER_TOTP_SECRET = os.getenv("BROKER_TOTP_SECRET", "")

# --- Backtest Universe (wider NIFTY large-cap sample for statistically meaningful results) ---
BACKTEST_UNIVERSE = WATCHLIST + [
    "TATAPOWER.NS", "WIPRO.NS", "LT.NS", "AXISBANK.NS", "KOTAKBANK.NS",
    "HINDUNILVR.NS", "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "BAJFINANCE.NS",
    "ASIANPAINT.NS", "ULTRACEMCO.NS", "NTPC.NS", "POWERGRID.NS", "M&M.NS",
    "TATASTEEL.NS", "HCLTECH.NS", "TECHM.NS", "ADANIPORTS.NS", "NESTLEIND.NS",
    "ONGC.NS", "COALINDIA.NS", "JSWSTEEL.NS", "DRREDDY.NS", "CIPLA.NS",
    "EICHERMOT.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "GRASIM.NS", "TRENT.NS",
]
BACKTEST_PERIOD = "10y"
BACKTEST_SPLIT_DATE = "2022-01-01"  # Parameters were tuned only on data before this date

# --- Realistic NSE delivery costs (per side): STT 0.1% + exchange, stamp duty, SEBI, GST ---
STATUTORY_COST_PCT = 0.0011

# --- Momentum Rotation Strategy (monthly) ---
MOMENTUM_LOOKBACK_DAYS = 252      # 12-month return...
MOMENTUM_SKIP_DAYS = 21           # ...excluding the most recent month (classic 12-1 momentum)
MOMENTUM_TOP_N = 8                # Equal-weight the 8 strongest stocks
MOMENTUM_REGIME_SMA = 200         # Hold cash when NIFTY is below its 200-day average
MOMENTUM_BUFFER_N = 12            # Keep a holding while it still ranks in the top 12 (cuts turnover/costs)

# --- Idle cash is parked in a liquid ETF (e.g. LIQUIDBEES) instead of earning nothing ---
CASH_YIELD_PCT = 0.055            # Conservative annual yield after expenses

# --- Pullback Swing Strategy (tuned on 2017-2021, validated on 2022-2026) ---
PULLBACK_STOP_ATR = 2.5
PULLBACK_TARGET_R = 3.0
PULLBACK_MAX_POSITION_PCT = 0.25
