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
