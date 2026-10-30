"""
Multi-Market Algorithmic Trading Agent - Production FastAPI Backend & Live WebSocket Server
Supports: Crypto 24/7 (Binance Real-Time Streaming) and Indian Equities (NSE)
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
import json
import os
import sqlite3
import sys
import subprocess
import threading
import time as time_module
from typing import Dict, List, Optional
import uuid
import urllib.request
import urllib.parse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pandas as pd
import numpy as np
import yfinance as yf

# Configuration
INITIAL_CAPITAL = 100000.0  # ₹1,00,000 INR starting capital (~$1,176 USD)
USD_INR_RATE = None         # live USD/INR from Yahoo (INR=X), set before the engine starts, refreshed every 60s
MAX_DAILY_LOSS_PCT = 0.02   # 2% loss halts trading and squares off (config.py's limit)
HIGH_RISK_LOSS_PCT = 0.05   # 5% in HIGH risk mode (it was 40%, which let one session burn 40% of capital)
RISK_PER_TRADE_PCT = 0.01   # 1% risk per trade
# Strictly live prices: every fill is the live quote itself, with no simulated slippage or brokerage
# (there is no broker, so any fee would be invented). Real trading would add real costs on top.
BROKERAGE_PER_ORDER = 0.0
MAX_QUOTE_AGE = {"CRYPTO": 10.0, "NSE": 120.0}   # seconds; an older quote is not a live price


def fetch_usd_inr() -> float:
    """The live USD/INR rate from Yahoo's INR=X quote. Raises if neither host answers."""
    last = None
    for host in ("query2", "query1"):
        try:
            url = "https://%s.finance.yahoo.com/v8/finance/chart/INR=X?range=1d&interval=1m" % host
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                rate = float(json.loads(r.read())["chart"]["result"][0]["meta"]["regularMarketPrice"])
            if rate > 0:
                return rate
        except Exception as e:
            last = e
    raise RuntimeError("could not fetch the live USD/INR rate from Yahoo: %s" % last)


def refresh_usd_inr():
    global USD_INR_RATE
    while True:
        time_module.sleep(60.0)
        try:
            USD_INR_RATE = fetch_usd_inr()
        except RuntimeError as e:
            print(f"[FX] {e}; keeping the last live rate {USD_INR_RATE}")

# Unified Multi-Market Asset Catalog
ASSETS = {
    # --- Indian Equities (NSE) ---
    "RELIANCE": {"ticker": "RELIANCE.NS", "name": "Reliance Industries Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:RELIANCE", "min_qty": 1, "step": 1},
    "TCS": {"ticker": "TCS.NS", "name": "Tata Consultancy Services Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:TCS", "min_qty": 1, "step": 1},
    "INFY": {"ticker": "INFY.NS", "name": "Infosys Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:INFY", "min_qty": 1, "step": 1},
    "HDFCBANK": {"ticker": "HDFCBANK.NS", "name": "HDFC Bank Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:HDFCBANK", "min_qty": 1, "step": 1},
    "ICICIBANK": {"ticker": "ICICIBANK.NS", "name": "ICICI Bank Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:ICICIBANK", "min_qty": 1, "step": 1},
    "SBIN": {"ticker": "SBIN.NS", "name": "State Bank of India", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:SBIN", "min_qty": 1, "step": 1},
    "BHARTIARTL": {"ticker": "BHARTIARTL.NS", "name": "Bharti Airtel Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:BHARTIARTL", "min_qty": 1, "step": 1},
    "ITC": {"ticker": "ITC.NS", "name": "ITC Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:ITC", "min_qty": 1, "step": 1},
    "TATAPOWER": {"ticker": "TATAPOWER.NS", "name": "Tata Power Company Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:TATAPOWER", "min_qty": 1, "step": 1},
    "WIPRO": {"ticker": "WIPRO.NS", "name": "Wipro Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:WIPRO", "min_qty": 1, "step": 1},
    "LT": {"ticker": "LT.NS", "name": "Larsen & Toubro Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:LT", "min_qty": 1, "step": 1},
    "AXISBANK": {"ticker": "AXISBANK.NS", "name": "Axis Bank Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:AXISBANK", "min_qty": 1, "step": 1},
    "KOTAKBANK": {"ticker": "KOTAKBANK.NS", "name": "Kotak Mahindra Bank Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:KOTAKBANK", "min_qty": 1, "step": 1},
    "HINDUNILVR": {"ticker": "HINDUNILVR.NS", "name": "Hindustan Unilever Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:HINDUNILVR", "min_qty": 1, "step": 1},
    "MARUTI": {"ticker": "MARUTI.NS", "name": "Maruti Suzuki India Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:MARUTI", "min_qty": 1, "step": 1},
    "SUNPHARMA": {"ticker": "SUNPHARMA.NS", "name": "Sun Pharmaceutical Industries Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:SUNPHARMA", "min_qty": 1, "step": 1},
    "TITAN": {"ticker": "TITAN.NS", "name": "Titan Company Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:TITAN", "min_qty": 1, "step": 1},
    "BAJFINANCE": {"ticker": "BAJFINANCE.NS", "name": "Bajaj Finance Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:BAJFINANCE", "min_qty": 1, "step": 1},
    "ASIANPAINT": {"ticker": "ASIANPAINT.NS", "name": "Asian Paints Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:ASIANPAINT", "min_qty": 1, "step": 1},
    "ULTRACEMCO": {"ticker": "ULTRACEMCO.NS", "name": "UltraTech Cement Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:ULTRACEMCO", "min_qty": 1, "step": 1},
    "NTPC": {"ticker": "NTPC.NS", "name": "NTPC Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:NTPC", "min_qty": 1, "step": 1},
    "POWERGRID": {"ticker": "POWERGRID.NS", "name": "Power Grid Corporation of India Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:POWERGRID", "min_qty": 1, "step": 1},
    "M&M": {"ticker": "M&M.NS", "name": "Mahindra & Mahindra Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:M_M", "min_qty": 1, "step": 1},
    "TATASTEEL": {"ticker": "TATASTEEL.NS", "name": "Tata Steel Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:TATASTEEL", "min_qty": 1, "step": 1},
    "HCLTECH": {"ticker": "HCLTECH.NS", "name": "HCL Technologies Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:HCLTECH", "min_qty": 1, "step": 1},
    "TECHM": {"ticker": "TECHM.NS", "name": "Tech Mahindra Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:TECHM", "min_qty": 1, "step": 1},
    "ADANIPORTS": {"ticker": "ADANIPORTS.NS", "name": "Adani Ports and SEZ Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:ADANIPORTS", "min_qty": 1, "step": 1},
    "NESTLEIND": {"ticker": "NESTLEIND.NS", "name": "Nestle India Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:NESTLEIND", "min_qty": 1, "step": 1},
    "ONGC": {"ticker": "ONGC.NS", "name": "Oil and Natural Gas Corporation Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:ONGC", "min_qty": 1, "step": 1},
    "COALINDIA": {"ticker": "COALINDIA.NS", "name": "Coal India Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:COALINDIA", "min_qty": 1, "step": 1},
    "JSWSTEEL": {"ticker": "JSWSTEEL.NS", "name": "JSW Steel Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:JSWSTEEL", "min_qty": 1, "step": 1},
    "DRREDDY": {"ticker": "DRREDDY.NS", "name": "Dr. Reddy's Laboratories Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:DRREDDY", "min_qty": 1, "step": 1},
    "CIPLA": {"ticker": "CIPLA.NS", "name": "Cipla Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:CIPLA", "min_qty": 1, "step": 1},
    "EICHERMOT": {"ticker": "EICHERMOT.NS", "name": "Eicher Motors Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:EICHERMOT", "min_qty": 1, "step": 1},
    "BAJAJ-AUTO": {"ticker": "BAJAJ-AUTO.NS", "name": "Bajaj Auto Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:BAJAJ_AUTO", "min_qty": 1, "step": 1},
    "HEROMOTOCO": {"ticker": "HEROMOTOCO.NS", "name": "Hero MotoCorp Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:HEROMOTOCO", "min_qty": 1, "step": 1},
    "GRASIM": {"ticker": "GRASIM.NS", "name": "Grasim Industries Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:GRASIM", "min_qty": 1, "step": 1},
    "TRENT": {"ticker": "TRENT.NS", "name": "Trent Ltd", "category": "NSE", "currency": "INR", "currency_symbol": "₹", "tv": "NSE:TRENT", "min_qty": 1, "step": 1},

    # --- Crypto Assets (24/7 Continuous Trading) ---
    "BTC": {"ticker": "BTC-USD", "name": "Bitcoin", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:BTCUSDT", "min_qty": 0.001, "step": 0.001},
    "ETH": {"ticker": "ETH-USD", "name": "Ethereum", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:ETHUSDT", "min_qty": 0.01, "step": 0.01},
    "SOL": {"ticker": "SOL-USD", "name": "Solana", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:SOLUSDT", "min_qty": 0.1, "step": 0.1},
    "DOGE": {"ticker": "DOGE-USD", "name": "Dogecoin", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:DOGEUSDT", "min_qty": 10.0, "step": 1.0},
    "BNB": {"ticker": "BNB-USD", "name": "Binance Coin", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:BNBUSDT", "min_qty": 0.05, "step": 0.05},
    "XRP": {"ticker": "XRP-USD", "name": "XRP Ripple", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:XRPUSDT", "min_qty": 1.0, "step": 1.0},
    "ADA": {"ticker": "ADA-USD", "name": "Cardano", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:ADAUSDT", "min_qty": 0.1, "step": 0.1},
    "TRX": {"ticker": "TRX-USD", "name": "TRON", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:TRXUSDT", "min_qty": 0.1, "step": 0.1},
    "AVAX": {"ticker": "AVAX-USD", "name": "Avalanche", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:AVAXUSDT", "min_qty": 0.01, "step": 0.01},
    "LINK": {"ticker": "LINK-USD", "name": "Chainlink", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:LINKUSDT", "min_qty": 0.01, "step": 0.01},
    "DOT": {"ticker": "DOT-USD", "name": "Polkadot", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:DOTUSDT", "min_qty": 0.01, "step": 0.01},
    "LTC": {"ticker": "LTC-USD", "name": "Litecoin", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:LTCUSDT", "min_qty": 0.001, "step": 0.001},
    "BCH": {"ticker": "BCH-USD", "name": "Bitcoin Cash", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:BCHUSDT", "min_qty": 0.001, "step": 0.001},
    "XLM": {"ticker": "XLM-USD", "name": "Stellar", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:XLMUSDT", "min_qty": 1, "step": 1},
    "HBAR": {"ticker": "HBAR-USD", "name": "Hedera", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:HBARUSDT", "min_qty": 1, "step": 1},
    "NEAR": {"ticker": "NEAR-USD", "name": "NEAR Protocol", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:NEARUSDT", "min_qty": 0.1, "step": 0.1},
    "ATOM": {"ticker": "ATOM-USD", "name": "Cosmos", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:ATOMUSDT", "min_qty": 0.01, "step": 0.01},
    "ETC": {"ticker": "ETC-USD", "name": "Ethereum Classic", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:ETCUSDT", "min_qty": 0.01, "step": 0.01},
    "FIL": {"ticker": "FIL-USD", "name": "Filecoin", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:FILUSDT", "min_qty": 0.01, "step": 0.01},
    "ICP": {"ticker": "ICP-USD", "name": "Internet Computer", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:ICPUSDT", "min_qty": 0.01, "step": 0.01},
    "OP": {"ticker": "OP-USD", "name": "Optimism", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:OPUSDT", "min_qty": 0.01, "step": 0.01},
    "INJ": {"ticker": "INJ-USD", "name": "Injective", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:INJUSDT", "min_qty": 0.01, "step": 0.01},
    "AAVE": {"ticker": "AAVE-USD", "name": "Aave", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:AAVEUSDT", "min_qty": 0.001, "step": 0.001}
}

# Major Indices and Benchmarks
INDICES_TICKERS = {
    "NIFTY 50": {"ticker": "^NSEI", "category": "NSE", "currency": "INR"},
    "SENSEX": {"ticker": "^BSESN", "category": "NSE", "currency": "INR"},
    "BANK NIFTY": {"ticker": "^NSEBANK", "category": "NSE", "currency": "INR"},
    "BITCOIN": {"ticker": "BTC-USD", "category": "CRYPTO", "currency": "USD"}
}

DB_PATH = os.path.join(os.path.dirname(__file__), "trading.db")

def persist_trade_async(order_record: dict, trade_record: Optional[dict] = None):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO orders (order_id, symbol, side, order_type, quantity, price, trigger_price, filled_price, stop_loss, target, status, tag, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_record["order_id"], order_record["symbol"], order_record["side"],
            order_record["order_type"], order_record["quantity"], order_record["price"],
            order_record["trigger_price"], order_record["filled_price"], order_record["stop_loss"],
            order_record["target"], order_record["status"], order_record["tag"], order_record["timestamp"]
        ))
        if trade_record and trade_record.get("pnl") != 0.0:
            c.execute("""
                INSERT INTO trades (trade_id, order_id, symbol, side, quantity, price, pnl, timestamp, tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_record["trade_id"], trade_record["order_id"], trade_record["symbol"],
                trade_record["side"], trade_record["quantity"], trade_record["price"],
                trade_record["pnl"], trade_record["timestamp"], trade_record["tag"]
            ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB Error] {e}")


# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            order_type TEXT,
            quantity REAL,
            price REAL,
            trigger_price REAL,
            filled_price REAL,
            stop_loss REAL,
            target REAL,
            status TEXT,
            tag TEXT,
            timestamp TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id TEXT PRIMARY KEY,
            order_id TEXT,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            price REAL,
            pnl REAL,
            timestamp TEXT,
            tag TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Normalization helper
def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        s = s.split(".")[0]
    if s.endswith("-USD"):
        s = s.split("-")[0]
    return s

def get_asset_meta(clean_symbol: str) -> dict:
    if clean_symbol in ASSETS:
        return ASSETS[clean_symbol]
    # Fallback heuristic
    if "-USD" in clean_symbol or clean_symbol in ["BTC", "ETH", "SOL", "DOGE", "BNB", "XRP"]:
        return {
            "ticker": f"{clean_symbol}-USD" if not clean_symbol.endswith("-USD") else clean_symbol,
            "name": clean_symbol,
            "category": "CRYPTO",
            "currency": "USD",
            "currency_symbol": "$",
            "tv": f"BINANCE:{clean_symbol}USDT",
            "min_qty": 0.01,
            "step": 0.01
        }
    return {
        "ticker": f"{clean_symbol}.NS",
        "name": clean_symbol,
        "category": "NSE",
        "currency": "INR",
        "currency_symbol": "₹",
        "tv": f"NSE:{clean_symbol}",
        "min_qty": 1,
        "step": 1
    }

# --- Trading Models ---
class OrderRequest(BaseModel):
    symbol: str
    side: str  # "BUY" or "SELL"
    order_type: str = "MARKET"  # "MARKET", "LIMIT", "SL"
    quantity: float = 1.0       # Supports decimals for crypto (e.g. 0.05 BTC) and integers for stocks
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    tag: Optional[str] = "MANUAL"

class AutoPilotConfig(BaseModel):
    enabled: Optional[bool] = None
    target_symbol: Optional[str] = None
    market: Optional[str] = None  # "CRYPTO" or "NSE" (Trade ONLY one market at a time!)
    mode: Optional[str] = None  # "MULTI" (all coins in market) or "SELECTED"
    speed: Optional[str] = None  # "HYPER" (30-60s), "ACTIVE" (2-5m), "SWING" (15m+)
    risk: Optional[str] = None  # "HIGH" (Heavy allocation) or "NORMAL"; None keeps the current one

class AutoPilotToggle(BaseModel):
    enabled: bool


# --- Trading Engine State ---
class TradingEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.capital = INITIAL_CAPITAL
        self.cash = INITIAL_CAPITAL
        # realized P&L of every closed trade at live prices, per currency (USD converts at the live rate)
        self.realized_native = {"INR": 0.0, "USD": 0.0}
        self.brokerage_paid = 0.0    # every order's brokerage, in INR (0: no simulated fees)
        self.closed_trades = 0
        self.positions: Dict[str, dict] = {}
        self.orders: List[dict] = []
        self.trade_history: List[dict] = []
        self.market_data: Dict[str, dict] = {}
        self.indices_data: Dict[str, dict] = {}
        self.tick_history: Dict[str, list] = {s: [] for s in ASSETS.keys()}
        self.circuit_broken = False
        self.auto_pilot = False
        self.autopilot_market = "CRYPTO"  # "CRYPTO" or "NSE" - strictly one market at a time!
        self.autopilot_target_symbol = "BTC"
        self.autopilot_mode = "MULTI"     # "MULTI" (trades ANY coin in active market) or "SELECTED"
        self.autopilot_speed = "HYPER"    # "HYPER" (fast execution)
        self.autopilot_risk = "NORMAL"    # "HIGH" (Heavy allocation) or "NORMAL"
        self.position_open_time: Dict[str, float] = {}
        self.last_exit_time: Dict[str, float] = {}
        self.autopilot_status = {
            "symbol": "CRYPTO",
            "state": "IDLE",
            "message": "Auto-Pilot Multi-Coin Quantum Engine ready. Trading across all active crypto pairs.",
            "last_action": None,
            "last_action_time": None
        }
        self.subscribers: List[WebSocket] = []
        self._load_state()

    def _load_state(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("SELECT * FROM orders ORDER BY timestamp DESC LIMIT 50")
        for row in c.fetchall():
            self.orders.append(dict(row))

        c.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 50")
        for row in c.fetchall():
            t = dict(row)
            t["currency"] = ASSETS.get(t["symbol"], {}).get("currency", "INR")   # crypto P&L is in USD
            self.trade_history.append(t)

        # Rebuild cash, positions and P&L from EVERY saved order, not only the last 50
        c.execute("SELECT * FROM orders ORDER BY timestamp ASC")
        self._replay([dict(r) for r in c.fetchall()])

        c.execute("SELECT key, value FROM config")
        for row in c.fetchall():
            k, v = row["key"], row["value"]
            if k == "auto_pilot":
                self.auto_pilot = (v == "true")
            elif k == "autopilot_market":
                self.autopilot_market = v
            elif k == "autopilot_target_symbol":
                self.autopilot_target_symbol = v
            elif k == "autopilot_mode":
                self.autopilot_mode = v
            elif k == "autopilot_speed":
                self.autopilot_speed = v
            elif k == "autopilot_risk":
                self.autopilot_risk = v
        conn.close()

    def _replay(self, orders: List[dict]):
        """Cash, positions and realized P&L from the full order log (oldest first), with the same
        arithmetic as place_order, so a restart shows the true account. Every fill is valued at the
        live quote stored with the order ("price"), not at a fill worsened by old simulated slippage."""
        for o in orders:
            if o.get("status") != "FILLED" or not o.get("filled_price"):
                continue
            sym = o["symbol"]
            meta = ASSETS.get(sym, {})
            curr = meta.get("currency", "INR")
            rate = USD_INR_RATE if curr == "USD" else 1.0
            live = o.get("price") if str(o.get("order_type", "")).upper() == "MARKET" else None
            px, qty = float(live or o["filled_price"]), float(o["quantity"])
            buy = str(o["side"]).upper() == "BUY"
            self.cash += (-px * qty * rate if buy else px * qty * rate) - BROKERAGE_PER_ORDER
            self.brokerage_paid += BROKERAGE_PER_ORDER
            pos = self.positions.setdefault(sym, {
                "symbol": sym, "name": meta.get("name", sym), "category": meta.get("category", "NSE"),
                "currency": curr, "currency_symbol": meta.get("currency_symbol", "₹"), "quantity": 0.0,
                "avg_price": 0.0, "stop_loss": None, "target": None, "realized_pnl": 0.0,
                "unrealized_pnl": 0.0, "ltp": px})
            fill = qty if buy else -qty
            old = pos["quantity"]
            new = round(old + fill, 6)
            if old == 0:
                pos["avg_price"], pos["stop_loss"], pos["target"] = px, o.get("stop_loss"), o.get("target")
            elif (old > 0) == (fill > 0):
                pos["avg_price"] = (abs(old) * pos["avg_price"] + qty * px) / abs(new)
            else:
                closed = min(abs(old), qty)
                delta = ((px - pos["avg_price"]) if old > 0 else (pos["avg_price"] - px)) * closed
                pos["realized_pnl"] += delta
                self.realized_native[curr] += delta
                self.closed_trades += 1
                if new == 0:
                    pos["avg_price"], pos["stop_loss"], pos["target"] = 0.0, None, None
                elif (old > 0) != (new > 0):
                    pos["avg_price"] = px
            pos["quantity"] = new
            pos["ltp"] = px

    def get_market_status(self) -> dict:
        now = datetime.now()
        current_time = now.time()
        is_weekday = now.weekday() < 5

        # Indian Market (NSE): 09:15 - 15:30 IST
        nse_open = time(9, 15)
        nse_close = time(15, 30)
        nse_is_open = is_weekday and (nse_open <= current_time <= nse_close)

        # Crypto Market: 24/7 Continuous
        crypto_is_open = True

        return {
            "is_open": nse_is_open or crypto_is_open,
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "nse": {
                "status": "OPEN" if nse_is_open else "CLOSED",
                "hours": "09:15 - 15:30 IST",
                "is_open": nse_is_open
            },
            "crypto": {
                "status": "OPEN 24/7",
                "hours": "24/7/365 Continuous",
                "is_open": True
            },
            "circuit_breaker": self.circuit_broken,
            "auto_pilot": self.auto_pilot,
            "autopilot_market": self.autopilot_market,
            "autopilot_target_symbol": self.autopilot_target_symbol,
            "autopilot_mode": self.autopilot_mode,
            "autopilot_speed": self.autopilot_speed,
            "autopilot_risk": self.autopilot_risk,
            "autopilot_status": self.autopilot_status
        }

    def square_off_closed_markets(self) -> List[dict]:
        status = self.get_market_status()
        to_close = []
        with self.lock:
            for sym, pos in self.positions.items():
                if pos.get("quantity", 0) != 0:
                    cat = pos.get("category", "")
                    if cat == "NSE" and not status["nse"]["is_open"]:
                        to_close.append(sym)

        results = []
        for sym in to_close:
            try:
                res = self.square_off_position(sym)
                results.append(res)
            except Exception as e:
                print(f"Error squaring off {sym}: {e}")
        return results

    def place_order(self, req: OrderRequest) -> dict:
        with self.lock:
            if self.circuit_broken:
                raise HTTPException(status_code=400, detail="RMS Circuit Breaker Active. Trading is locked.")

            clean_symbol = normalize_symbol(req.symbol)
            meta = get_asset_meta(clean_symbol)
            ticker = meta["ticker"]
            curr = meta["currency"]
            c_sym = meta["currency_symbol"]
            cat = meta["category"]
            rate = USD_INR_RATE if curr == "USD" else 1.0

            market_status = self.get_market_status()
            is_market_open = True
            if cat == "NSE":
                is_market_open = market_status["nse"]["is_open"]
            elif cat == "CRYPTO":
                is_market_open = True

            is_exit_or_rms = (req.tag in ["SQUARE_OFF", "AUTO_SL", "AUTO_TARGET", "AUTOPILOT_TAKE_PROFIT", "AUTOPILOT_STOP_LOSS", "AUTOPILOT_TRAILING_PROFIT", "AUTOPILOT_PEAK_PROFIT", "AUTOPILOT_PROFIT_PULL", "AUTOPILOT_ROTATION", "AUTOPILOT_BREAK_EVEN", "AUTOPILOT_TARGET_HIT"]) or ("EXIT" in str(req.tag)) or ("PROFIT" in str(req.tag)) or ("STOP" in str(req.tag)) or ("BREAK_EVEN" in str(req.tag))

            # 0. An exit only ever reduces a position. Two exits can fire together (the tick stop-loss and the
            #    Auto-Pilot's own exit); the second must not flip the trade into the opposite side.
            if is_exit_or_rms:
                held = self.positions.get(clean_symbol, {}).get("quantity", 0)
                reduces = (held > 0 and req.side.upper() == "SELL") or (held < 0 and req.side.upper() == "BUY")
                if not reduces:
                    raise HTTPException(status_code=409, detail=f"{clean_symbol}: nothing to close (already flat)")
                req.quantity = min(req.quantity, abs(held))

            # 1. STRICT GUARD: Auto-Pilot orders MUST NOT execute on closed markets or outside active single market
            if req.tag and req.tag.startswith("AUTOPILOT_") and not is_exit_or_rms:
                if self.autopilot_market and cat != self.autopilot_market:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Auto-Pilot blocked: Active market is {self.autopilot_market}. Cannot trade {cat} assets."
                    )
                if not is_market_open:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Auto-Pilot blocked: {cat} market for {clean_symbol} is currently CLOSED. Auto-Pilot only trades open markets."
                    )
                if self.autopilot_mode == "SELECTED" and clean_symbol != self.autopilot_target_symbol:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Auto-Pilot blocked: {clean_symbol} is not your selected target ({self.autopilot_target_symbol})."
                    )

            # 2. STRICT GUARD: Manual new orders on closed markets
            if not is_exit_or_rms and not is_market_open:
                hours_str = market_status[cat.lower()]["hours"] if cat.lower() in market_status else "Closed"
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot place order: {cat} market for {clean_symbol} is currently CLOSED ({hours_str}). Crypto 24/7 is currently open."
                )

            # Strictly live: fill at the latest real quote, never at a made-up or stale price
            quote = self.market_data.get(clean_symbol, {})
            ltp = quote.get("ltp")
            age = time_module.time() - quote.get("quote_time", 0)
            if not ltp:
                raise HTTPException(status_code=503, detail=f"No live price for {clean_symbol} yet: order not filled.")
            if age > MAX_QUOTE_AGE.get(cat, 120.0):
                raise HTTPException(status_code=503, detail=f"The {clean_symbol} quote is {age:.0f}s old, not live: "
                                                            f"order not filled.")
            if curr == "USD" and not USD_INR_RATE:
                raise HTTPException(status_code=503, detail="No live USD/INR rate: order not filled.")

            order_id = f"ORD_{uuid.uuid4().hex[:8].upper()}"
            fill_price = ltp   # the live quote itself: no simulated slippage, no rounding

            # Check Margin Requirement in INR
            trade_value_native = fill_price * req.quantity
            trade_value_inr = trade_value_native * rate
            brokerage_inr = BROKERAGE_PER_ORDER

            existing_pos = self.positions.get(clean_symbol)
            is_closing_short = (existing_pos is not None and existing_pos.get("quantity", 0) < 0 and req.side.upper() == "BUY")

            if req.side.upper() == "BUY" and not is_closing_short and not is_exit_or_rms:
                required_funds = trade_value_inr + brokerage_inr
                if self.cash < (required_funds - 100.0):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient Margin. Required: Rs.{required_funds:,.2f} ({c_sym}{trade_value_native:,.2f}), Available: Rs.{self.cash:,.2f}"
                    )
                self.cash -= (trade_value_inr + brokerage_inr)
            elif req.side.upper() == "BUY":
                # Closing short / exit: execute without margin rejection
                self.cash -= (trade_value_inr + brokerage_inr)
            else:
                self.cash += (trade_value_inr - brokerage_inr)
            self.brokerage_paid += brokerage_inr

            order_record = {
                "order_id": order_id,
                "symbol": clean_symbol,
                "side": req.side.upper(),
                "order_type": req.order_type.upper(),
                "quantity": req.quantity,
                "price": req.price or ltp,
                "trigger_price": None,
                "filled_price": fill_price,
                "stop_loss": req.stop_loss,
                "target": req.target,
                "currency": curr,
                "currency_symbol": c_sym,
                "category": meta["category"],
                "status": "FILLED",
                "tag": req.tag or "MANUAL",
                "timestamp": datetime.now().isoformat()
            }

            # Update Position
            pos = self.positions.get(clean_symbol, {
                "symbol": clean_symbol,
                "name": meta["name"],
                "category": meta["category"],
                "currency": curr,
                "currency_symbol": c_sym,
                "quantity": 0.0,
                "avg_price": 0.0,
                "stop_loss": req.stop_loss,
                "target": req.target,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "ltp": ltp
            })

            fill_qty = req.quantity if req.side.upper() == "BUY" else -req.quantity
            old_qty = pos["quantity"]
            new_qty = round(old_qty + fill_qty, 6)

            realized_delta = 0.0
            if old_qty == 0:
                pos["avg_price"] = fill_price
                pos["quantity"] = new_qty
                pos["stop_loss"] = req.stop_loss
                pos["target"] = req.target
                # A new trade starts with no peak: the position dict is reused after a close, and an
                # inherited peak made the Break-Even Shield sell every new trade within a second.
                pos["max_profit_pct"] = 0.0
                self.position_open_time[clean_symbol] = time_module.time()
            elif (old_qty > 0 and fill_qty > 0) or (old_qty < 0 and fill_qty < 0):
                total_cost = (abs(old_qty) * pos["avg_price"]) + (abs(fill_qty) * fill_price)
                pos["quantity"] = new_qty
                pos["avg_price"] = total_cost / abs(new_qty)   # exact average of live fills
                if req.stop_loss: pos["stop_loss"] = req.stop_loss
                if req.target: pos["target"] = req.target
            else:
                # Closing or flipping
                closed_qty = min(abs(old_qty), abs(fill_qty))
                if old_qty > 0:
                    realized_delta = (fill_price - pos["avg_price"]) * closed_qty
                else:
                    realized_delta = (pos["avg_price"] - fill_price) * closed_qty

                pos["realized_pnl"] += realized_delta
                self.realized_native[curr] += realized_delta   # exact; rounded only when shown
                self.closed_trades += 1
                pos["quantity"] = new_qty
                if new_qty == 0:
                    pos["avg_price"] = 0.0
                    pos["stop_loss"] = None
                    pos["target"] = None
                    self.position_open_time.pop(clean_symbol, None)
                    self.last_exit_time[clean_symbol] = time_module.time()
                elif (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0):
                    pos["avg_price"] = fill_price
                    pos["max_profit_pct"] = 0.0
                    self.position_open_time[clean_symbol] = time_module.time()

            # Update unrealized
            if pos["quantity"] > 0:
                pos["unrealized_pnl"] = round((ltp - pos["avg_price"]) * pos["quantity"], 2)
            elif pos["quantity"] < 0:
                pos["unrealized_pnl"] = round((pos["avg_price"] - ltp) * abs(pos["quantity"]), 2)
            else:
                pos["unrealized_pnl"] = 0.0

            pos["ltp"] = ltp
            self.positions[clean_symbol] = pos

            # Record Trade in History
            trade_record = {
                "trade_id": f"TRD_{uuid.uuid4().hex[:8].upper()}",
                "order_id": order_id,
                "symbol": clean_symbol,
                "side": req.side.upper(),
                "quantity": req.quantity,
                "price": fill_price,
                "pnl": realized_delta,
                "currency": curr,
                "timestamp": datetime.now().isoformat(),
                "tag": req.tag or "MANUAL"
            }

            self.orders.insert(0, order_record)
            if realized_delta != 0.0:
                self.trade_history.insert(0, trade_record)

            # Instant In-Memory Execution: Offload SQLite disk I/O to background thread
            threading.Thread(
                target=persist_trade_async,
                args=(order_record, trade_record if realized_delta != 0.0 else None),
                daemon=True
            ).start()

            return order_record

    def square_off_position(self, symbol: str) -> dict:
        clean_symbol = normalize_symbol(symbol)
        with self.lock:
            pos = self.positions.get(clean_symbol)
            if not pos or pos["quantity"] == 0:
                raise HTTPException(status_code=400, detail="No open position for symbol.")

            side = "SELL" if pos["quantity"] > 0 else "BUY"
            qty = abs(pos["quantity"])

        req = OrderRequest(symbol=clean_symbol, side=side, quantity=qty, tag="SQUARE_OFF")
        return self.place_order(req)

    def square_off_all(self) -> List[dict]:
        results = []
        with self.lock:
            symbols = [sym for sym, pos in self.positions.items() if pos["quantity"] != 0]

        for s in symbols:
            try:
                res = self.square_off_position(s)
                results.append(res)
            except Exception as e:
                print(f"Error squaring off {s}: {e}")
        return results

    def reset_portfolio(self):
        with self.lock:
            self.square_off_all()
            self.capital = INITIAL_CAPITAL
            self.cash = INITIAL_CAPITAL
            self.realized_native = {"INR": 0.0, "USD": 0.0}
            self.brokerage_paid = 0.0
            self.closed_trades = 0
            self.positions = {}
            self.orders = []
            self.trade_history = []
            self.position_open_time = {}
            self.last_exit_time = {}
            self.circuit_broken = False
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM orders")
            c.execute("DELETE FROM trades")
            conn.commit()
            conn.close()

    def update_ticks(self, symbol: str, ltp: float):
        clean_symbol = normalize_symbol(symbol)
        with self.lock:
            if clean_symbol in self.positions:
                pos = self.positions[clean_symbol]
                pos["ltp"] = ltp
                qty = pos["quantity"]
                if qty > 0:
                    pos["unrealized_pnl"] = round((ltp - pos["avg_price"]) * qty, 2)
                elif qty < 0:
                    pos["unrealized_pnl"] = round((pos["avg_price"] - ltp) * abs(qty), 2)
                else:
                    pos["unrealized_pnl"] = 0.0

                # Check SL / Target Hit for Active Positions
                sl = pos.get("stop_loss")
                target = pos.get("target")

                hit_sl = False
                hit_target = False

                if qty > 0:
                    if sl and ltp <= sl: hit_sl = True
                    if target and ltp >= target: hit_target = True
                elif qty < 0:
                    if sl and ltp >= sl: hit_sl = True
                    if target and ltp <= target: hit_target = True

                if hit_sl or hit_target:
                    side = "SELL" if qty > 0 else "BUY"
                    tag = "AUTO_SL" if hit_sl else "AUTO_TARGET"
                    # Exit immediately (a "nothing to close" refusal just means another exit got there first)
                    threading.Thread(
                        target=self._exit_quietly,
                        args=(OrderRequest(symbol=clean_symbol, side=side, quantity=abs(qty), tag=tag),),
                        daemon=True
                    ).start()

    def _exit_quietly(self, req: OrderRequest):
        try:
            self.place_order(req)
        except HTTPException:
            pass

    def get_portfolio_summary(self) -> dict:
        with self.lock:
            total_unrealized_inr = 0.0
            open_positions = 0
            for sym, pos in self.positions.items():
                if pos["quantity"] != 0:
                    open_positions += 1
                    rate = USD_INR_RATE if pos.get("currency") == "USD" else 1.0
                    total_unrealized_inr += (pos.get("unrealized_pnl", 0.0) * rate)

            # Every closed trade (not just the last 50 in memory), at live prices; USD at the live rate
            total_realized_inr = (self.realized_native["INR"] + self.realized_native["USD"] * USD_INR_RATE
                                  - self.brokerage_paid)
            total_pnl_inr = round(total_realized_inr + total_unrealized_inr, 2)
            portfolio_val_inr = round(self.capital + total_pnl_inr, 2)

            # Check Circuit Breaker (5% in HIGH RISK mode, 2% otherwise)
            loss_pct = HIGH_RISK_LOSS_PCT if self.autopilot_risk == "HIGH" else MAX_DAILY_LOSS_PCT
            max_daily_loss = self.capital * loss_pct
            if total_pnl_inr <= -max_daily_loss and not self.circuit_broken:
                self.circuit_broken = True
                threading.Thread(target=self.square_off_all, daemon=True).start()

            return {
                "initial_capital": self.capital,
                "portfolio_value": portfolio_val_inr,
                "portfolio_value_usd": round(portfolio_val_inr / USD_INR_RATE, 2),
                "current_cash": round(self.cash, 2),
                "current_cash_usd": round(self.cash / USD_INR_RATE, 2),
                "realized_pnl": round(total_realized_inr, 2),
                "realized_pnl_usd": round(total_realized_inr / USD_INR_RATE, 2),
                "unrealized_pnl": round(total_unrealized_inr, 2),
                "unrealized_pnl_usd": round(total_unrealized_inr / USD_INR_RATE, 2),
                "total_pnl": total_pnl_inr,
                "return_pct": round((total_pnl_inr / self.capital) * 100, 2),
                "open_positions_count": open_positions,
                "total_trades_count": self.closed_trades,
                "brokerage_paid": round(self.brokerage_paid, 2),
                "max_daily_loss_limit": max_daily_loss,
                "max_daily_loss_pct": loss_pct * 100,
                "autopilot_risk": self.autopilot_risk,
                "circuit_breaker_active": self.circuit_broken,
                "usd_inr_rate": USD_INR_RATE
            }


# Singleton engine
# The live USD/INR rate is needed before the engine rebuilds the account; no rate, no start.
USD_INR_RATE = fetch_usd_inr()
engine = TradingEngine()


# --- Background Concurrent Market Poller ---
def fetch_crypto_data_binance() -> Dict[str, dict]:
    # every crypto asset, as its Binance USDT pair (all checked to trade on Binance spot, 2026-10-30)
    symbols_map = {k + "USDT": k for k, v in ASSETS.items() if v["category"] == "CRYPTO"}
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr?symbols=" + urllib.parse.quote(
            json.dumps(sorted(symbols_map), separators=(",", ":")))
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as r:
            items = json.loads(r.read())
        results = {}
        for item in items:
            sym_raw = item["symbol"]
            sym = symbols_map.get(sym_raw)
            if not sym or sym not in ASSETS:
                continue
            meta = ASSETS[sym]
            try:   # Binance's own numbers only; a ticker missing a field is skipped, never filled in
                ltp = float(item["lastPrice"])
                prev_close = float(item["prevClosePrice"])
                day_high = float(item["highPrice"])
                day_low = float(item["lowPrice"])
                vol = float(item["volume"])
                change_pct = float(item["priceChangePercent"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (ltp > 0 and prev_close > 0 and day_high > 0 and day_low > 0):   # NaN fails too
                continue

            trend = "STRONG UPTREND" if change_pct > 0.5 else ("DOWNTREND" if change_pct < -0.5 else "SIDEWAYS")
            is_vcp = abs(day_high - day_low) < (ltp * 0.02)
            is_breakout = ltp >= (day_high * 0.998)

            sl_price = round(day_low * 0.99, 4 if ltp < 10 else 2)
            risk_per_share = max(0.01, ltp - sl_price)
            max_inr_risk = 1000.0
            risk_in_native = max_inr_risk / USD_INR_RATE
            safe_qty = max(meta["min_qty"], round(risk_in_native / risk_per_share, 4))
            target_price = round(ltp + (2 * risk_per_share), 4 if ltp < 10 else 2)

            results[sym] = {
                "symbol": sym,
                "name": meta["name"],
                "ticker": meta["ticker"],
                "category": "CRYPTO",
                "currency": "USD",
                "currency_symbol": "$",
                "tv_symbol": meta["tv"],
                "ltp": ltp,                      # exact live last-trade price, not rounded
                "quote_time": time_module.time(),
                "prev_close": prev_close,
                "change_pct": round(change_pct, 2),
                "day_high": day_high,
                "day_low": day_low,
                "volume": int(vol),
                "trend": trend,
                "is_vcp": is_vcp,
                "is_breakout": is_breakout,
                "suggested_sl": sl_price,
                "suggested_target": target_price,
                "suggested_qty": safe_qty,
                "updated_at": datetime.now().strftime("%H:%M:%S")
            }
        return results
    except Exception as e:
        print(f"[Binance Fetch Error] {e}")
        return {}

def fetch_ticker_data(item):
    symbol, meta = item
    ticker = meta["ticker"]
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        # Yahoo's own numbers only: if one is missing this update is skipped, never filled in
        ltp = float(info['lastPrice'])
        prev_close = float(info['regularMarketPreviousClose'])
        if not np.isfinite(prev_close):   # Yahoo leaves this NaN for some NSE stocks; its previousClose is set
            prev_close = float(info['previousClose'])
        day_high = float(info['dayHigh'])
        day_low = float(info['dayLow'])
        vol = info['lastVolume']
        if not all(isinstance(x, (int, float)) and np.isfinite(x) and x > 0
                   for x in (ltp, prev_close, day_high, day_low)) or vol is None or not np.isfinite(vol):
            return symbol, None    # Yahoo sent a NaN or a zero: skip this update, never fill one in
        vol = int(vol)
        change_pct = round(((ltp - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

        # Trend & Technical Squeeze Detection
        trend = "STRONG UPTREND" if ltp > prev_close else ("DOWNTREND" if ltp < prev_close else "SIDEWAYS")
        is_vcp = abs(day_high - day_low) < (ltp * 0.02)
        is_breakout = ltp >= day_high

        # Suggested Risk-Controlled Position
        sl_price = round(day_low * 0.99, 4 if meta["category"] == "CRYPTO" and ltp < 10 else 2)
        risk_per_share = max(0.5 if meta["category"] != "CRYPTO" else 0.01, ltp - sl_price)
        max_inr_risk = 1000.0  # ₹1,000 risk per trade
        risk_in_native = max_inr_risk / (USD_INR_RATE if meta["currency"] == "USD" else 1.0)
        safe_qty = max(meta["min_qty"], round(risk_in_native / risk_per_share, 4 if meta["category"] == "CRYPTO" else 0))
        target_price = round(ltp + (2 * risk_per_share), 4 if meta["category"] == "CRYPTO" and ltp < 10 else 2)

        return symbol, {
            "symbol": symbol,
            "name": meta["name"],
            "ticker": ticker,
            "category": meta["category"],
            "currency": meta["currency"],
            "currency_symbol": meta["currency_symbol"],
            "tv_symbol": meta["tv"],
            "ltp": ltp,                          # exact live last price, not rounded
            "quote_time": time_module.time(),
            "prev_close": prev_close,
            "change_pct": change_pct,
            "day_high": day_high,
            "day_low": day_low,
            "volume": vol,
            "trend": trend,
            "is_vcp": is_vcp,
            "is_breakout": is_breakout,
            "suggested_sl": sl_price,
            "suggested_target": target_price,
            "suggested_qty": safe_qty,
            "updated_at": datetime.now().strftime("%H:%M:%S")
        }
    except Exception as e:
        return symbol, None


def background_equity_poller():
    """Poll Indian and US equities once every 45s so Yahoo Finance rate limits are never hit."""
    while True:
        try:
            now_str = datetime.now().strftime("%H:%M:%S")
            for name, meta in INDICES_TICKERS.items():
                if meta["category"] == "CRYPTO":
                    continue
                try:
                    t = yf.Ticker(meta["ticker"])
                    info = t.fast_info
                    lp = round(float(info['lastPrice']), 2)
                    pc = round(float(info.get('regularMarketPreviousClose', lp)), 2)
                    chg = round(lp - pc, 2)
                    chg_pct = round((chg / pc) * 100, 2) if pc else 0.0
                    engine.indices_data[name] = {
                        "name": name,
                        "category": meta["category"],
                        "currency": meta["currency"],
                        "value": lp,
                        "change": chg,
                        "change_pct": chg_pct,
                        "updated_at": now_str
                    }
                except Exception:
                    pass

            equity_items = [(k, v) for k, v in ASSETS.items() if v["category"] == "NSE"]
            with ThreadPoolExecutor(max_workers=6) as executor:
                fetched_eq = list(executor.map(fetch_ticker_data, equity_items))
            for sym, data in fetched_eq:
                if data:
                    engine.market_data[sym] = data
                    engine.update_ticks(sym, data["ltp"])
        except Exception as e:
            print(f"[Equity Poller Error] {e}")

        time_module.sleep(45.0)


def calc_ema(prices: List[float], period: int) -> float:
    """Calculate Exponential Moving Average over price series."""
    if not prices:
        return 0.0
    if len(prices) < period:
        return sum(prices) / len(prices)
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = (p * k) + (ema * (1.0 - k))
    return ema


def background_market_poller():
    """Continuously poll Crypto markets every 1s via Binance API (0 rate-limit) and run Auto-Pilot."""
    while True:
        try:
            now_str = datetime.now().strftime("%H:%M:%S")

            # 1. Update Crypto Assets every cycle via high-speed Binance API (sub-second, 0 rate limit)
            crypto_results = fetch_crypto_data_binance()

            # Update Bitcoin index
            if "BTC" in crypto_results:
                btc_d = crypto_results["BTC"]
                engine.indices_data["BITCOIN"] = {
                    "name": "BITCOIN",
                    "category": "CRYPTO",
                    "currency": "USD",
                    "value": btc_d["ltp"],
                    "change": round(btc_d["ltp"] - btc_d["prev_close"], 2),
                    "change_pct": btc_d["change_pct"],
                    "updated_at": now_str
                }

            for sym, data in crypto_results.items():
                if not data:
                    continue

                engine.market_data[sym] = data
                ltp = data["ltp"]

                # Append to rolling tick history (max 60 ticks)
                with engine.lock:
                    history = engine.tick_history.setdefault(sym, [])
                    history.append({"time": now_str, "price": ltp})
                    if len(history) > 60:
                        history.pop(0)

                engine.update_ticks(sym, ltp)

                # The Auto-Pilot no longer trades from here: its old tick-EMA entries lost money in every
                # backtest. It now runs the trading skills (skills_autotrader_loop); the dashboard holds each
                # order's stop and target (update_ticks) and the skills loop closes its trades at flat-by.
        except Exception as e:
            print(f"[Market Poller Error] {e}")

        time_module.sleep(1.0)  # Fast 1.0s concurrent tick cycle


# --- FastAPI App ---
app = FastAPI(title="Multi-Market Algorithmic Trading Terminal", version="2.0.0")

_pollers_started = False


@app.on_event("startup")
def start_pollers():
    """Start the market pollers (and the Auto-Pilot) once, when the web app starts. Starting them at
    import ran TWO engines under `python server.py` (the script, then uvicorn's own import of it):
    the hidden one kept trading the paper account with the Auto-Pilot the dashboard had turned off."""
    global _pollers_started
    if _pollers_started:
        return
    _pollers_started = True
    threading.Thread(target=refresh_usd_inr, daemon=True).start()
    threading.Thread(target=background_market_poller, daemon=True).start()
    threading.Thread(target=background_equity_poller, daemon=True).start()
    threading.Thread(target=skills_autotrader_loop, daemon=True).start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static dashboard
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def get_dashboard():
    # no-store: a cached copy would hide dashboard updates (like the Skills panel) after a restart
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers={"Cache-Control": "no-store"})

@app.get("/api/status")
def get_status():
    return engine.get_market_status()

@app.get("/api/portfolio")
def get_portfolio():
    return engine.get_portfolio_summary()

@app.get("/api/positions")
def get_positions():
    with engine.lock:
        return [p for p in engine.positions.values() if p["quantity"] != 0]

@app.get("/api/orders")
def get_orders():
    with engine.lock:
        return engine.orders[:40]

@app.get("/api/trades")
def get_trades():
    with engine.lock:
        return engine.trade_history[:40]

@app.get("/api/scanner")
def get_scanner():
    with engine.lock:
        return list(engine.market_data.values())

@app.get("/api/chart/{symbol}")
def get_chart_data(symbol: str):
    clean_sym = normalize_symbol(symbol)
    meta = get_asset_meta(clean_sym)
    ticker = meta["ticker"]
    try:
        df = yf.download(ticker, period="1mo", interval="1d", progress=False)
        if df.empty:
            raise HTTPException(status_code=404, detail="No chart data")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        candles = []
        for index, row in df.iterrows():
            candles.append({
                "time": index.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"])
            })
        return {"symbol": clean_sym, "candles": candles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/orders")
def create_order(req: OrderRequest):
    return engine.place_order(req)

@app.post("/api/positions/square-off/{symbol}")
def square_off(symbol: str):
    return engine.square_off_position(symbol)

@app.post("/api/positions/square-off-all")
def square_off_all():
    return engine.square_off_all()

@app.post("/api/positions/square-off-closed-markets")
def square_off_closed():
    return engine.square_off_closed_markets()

@app.get("/api/indices")
def get_indices():
    with engine.lock:
        return list(engine.indices_data.values())

@app.get("/api/ticks/{symbol}")
def get_ticks(symbol: str):
    clean_sym = normalize_symbol(symbol)
    with engine.lock:
        return engine.tick_history.get(clean_sym, [])

@app.post("/api/autopilot/config")
def config_autopilot(cfg: AutoPilotConfig):
    with engine.lock:
        if cfg.enabled is not None:
            engine.auto_pilot = cfg.enabled
        if cfg.market:
            engine.autopilot_market = cfg.market.upper()
        if cfg.target_symbol:
            engine.autopilot_target_symbol = normalize_symbol(cfg.target_symbol)
        if cfg.mode:
            engine.autopilot_mode = cfg.mode.upper()
        if cfg.speed:
            engine.autopilot_speed = cfg.speed.upper()
        if cfg.risk:
            engine.autopilot_risk = cfg.risk.upper()

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('auto_pilot', ?)", ('true' if engine.auto_pilot else 'false',))
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('autopilot_market', ?)", (engine.autopilot_market,))
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('autopilot_target_symbol', ?)", (engine.autopilot_target_symbol,))
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('autopilot_mode', ?)", (engine.autopilot_mode,))
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('autopilot_speed', ?)", (engine.autopilot_speed,))
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('autopilot_risk', ?)", (engine.autopilot_risk,))
        conn.commit()
        conn.close()

    return {
        "auto_pilot": engine.auto_pilot,
        "autopilot_market": engine.autopilot_market,
        "autopilot_target_symbol": engine.autopilot_target_symbol,
        "autopilot_mode": engine.autopilot_mode,
        "autopilot_speed": engine.autopilot_speed,
        "autopilot_risk": engine.autopilot_risk,
        "autopilot_status": engine.autopilot_status
    }

@app.post("/api/autopilot/toggle")
def toggle_autopilot(payload: dict):
    enabled = payload.get("enabled", not engine.auto_pilot)
    target = payload.get("target_symbol", engine.autopilot_target_symbol)
    mode = payload.get("mode", engine.autopilot_mode)
    speed = payload.get("speed", engine.autopilot_speed)
    risk = payload.get("risk", engine.autopilot_risk)
    return config_autopilot(AutoPilotConfig(enabled=enabled, target_symbol=target, mode=mode, speed=speed, risk=risk))

@app.post("/api/portfolio/reset")
def reset_portfolio():
    engine.reset_portfolio()
    return {"message": f"Portfolio reset to Rs.{INITIAL_CAPITAL:,.0f} (~${INITIAL_CAPITAL/USD_INR_RATE:,.0f} USD) calibrated for $100-$200 trade sizing"}


# --- Trading skills (.claude/skills): scan -> analyse -> size & risk -> your yes -> paper order ---
# Each step runs the real skill script and returns its own JSON, so the panel shows exactly what the
# skill computed. Files live in trader/ next to this server, the way the skills expect.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(BASE_DIR, ".claude", "skills")
TRADER_CFG = os.path.join(BASE_DIR, "trader", "config.json")
skills_lock = threading.Lock()   # one skill pipeline at a time: they share trader/*.json


def skills_config() -> dict:
    """trader/config.json; written once with 1 % risk per trade of the paper capital per market."""
    if os.path.exists(TRADER_CFG):
        with open(TRADER_CFG, encoding="utf-8") as fh:
            return json.load(fh)
    usd_budget = round(INITIAL_CAPITAL / USD_INR_RATE, 2)
    cfg = {
        "paper": True, "allow_crypto": True, "require_stop": True, "min_reward_risk": 1.0,
        "max_trades_per_day": 3, "max_orders_per_day": 10, "dashboard_url": "http://127.0.0.1:8001",
        "markets": {
            "nse": {"budget": INITIAL_CAPITAL, "max_loss_per_trade_usd": INITIAL_CAPITAL * 0.01,
                    "max_daily_loss_usd": INITIAL_CAPITAL * 0.02, "max_order_usd": INITIAL_CAPITAL * 0.5,
                    "min_order_usd": 500, "max_position_pct": 50, "cash_buffer_pct": 10, "broker": "dashboard",
                    "no_entries_before": "09:30", "no_entries_after": "14:45", "flat_by": "15:10"},
            "crypto": {"budget": usd_budget, "max_loss_per_trade_usd": round(usd_budget * 0.01, 2),
                       "max_daily_loss_usd": round(usd_budget * 0.02, 2), "max_order_usd": round(usd_budget * 0.5, 2),
                       "min_order_usd": 10, "max_position_pct": 50, "cash_buffer_pct": 10, "broker": "dashboard",
                       "fee_pct": 0.1, "flat_by": "23:55"},
        },
    }
    os.makedirs(os.path.dirname(TRADER_CFG), exist_ok=True)
    with open(TRADER_CFG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return cfg


def run_skill(script: str, args: List[str], timeout: float = 240.0, cwd: str = None) -> dict:
    """Run one skill script with --json in this folder (or cwd): {"ok", "code", "data", "text", "error"}."""
    proc = subprocess.run([sys.executable, os.path.join(SKILLS_DIR, script)] + args, cwd=cwd or BASE_DIR,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    data = None
    out = (proc.stdout or "").strip()
    if out.startswith("{") or out.startswith("["):
        try:
            data = json.loads(out)
        except ValueError:
            data = None
    err = (proc.stderr or "").strip().splitlines()
    err = [line for line in err if "Warning" not in line and not line.startswith("  ")]
    return {"ok": proc.returncode == 0, "code": proc.returncode, "data": data,
            "text": out if data is None else None, "error": err[-1] if err else None}


class SkillScan(BaseModel):
    market: str            # "nse" or "crypto"
    mode: str = "orb"      # "orb" (opening-range breakouts today) or "daily" (daily-close setups)


class SkillAnalyze(BaseModel):
    symbol: str            # RELIANCE.NS or BTC-USD
    stop: str = "or-mid"   # or-mid, or-low, pct:X, atr:K
    target: str = "2R"


class SkillPlace(BaseModel):
    reply: str             # the user's own words; only a plain "yes" approves


@app.get("/api/skills/config")
def skills_get_config():
    return skills_config()


@app.post("/api/skills/scan")
def skills_scan(req: SkillScan):
    if req.market not in ("nse", "crypto") or req.mode not in ("orb", "daily"):
        raise HTTPException(status_code=400, detail="market is nse or crypto; mode is orb or daily")
    skills_config()
    with skills_lock:
        args = [req.mode, "--market", req.market, "--json", "--quiet"]
        if req.mode == "orb":   # orb reads the entry cutoff (no_entries_after) from the config
            args += ["--config", TRADER_CFG]
        return run_skill("trader-scanner/scan.py", args)


@app.post("/api/skills/analyze")
def skills_analyze(req: SkillAnalyze):
    """Entry timer -> exit planner -> time machine, for one symbol, right now."""
    skills_config()
    sym = req.symbol.strip().upper()
    with skills_lock:
        entry = run_skill("trader-entry/entry.py", ["check", sym, "--write", "trader/entry.json", "--json",
                                                   "--config", TRADER_CFG])
        out = {"entry": entry, "plan": None, "timemachine": None}
        if not entry["data"] or entry["data"].get("status") != "triggered":
            return out
        plan = run_skill("trader-exit/exit.py", ["plan", "--from", "trader/entry.json", "--stop", req.stop,
                                                 "--target", req.target, "--config", TRADER_CFG,
                                                 "--write", "trader/plan.json", "--json"])
        out["plan"] = plan
        if not plan["ok"] or not plan["data"]:
            return out
        tm = run_skill("trader-timemachine/timemachine.py", ["run", "--plan", "trader/plan.json", "--until",
                                                            plan["data"]["flat_by"], "--write",
                                                            "trader/timemachine.json", "--json"])
        if tm["data"]:   # the fan chart's and sample paths' thousands of points are not needed in the panel
            for k in ("bands", "sample_paths", "band_times"):
                tm["data"]["mc"].pop(k, None)
        out["timemachine"] = tm
        return out


@app.post("/api/skills/size")
def skills_size():
    """Budget sizer -> risk check -> the ticket, for the plan from the last analysis."""
    skills_config()
    with skills_lock:
        # The live quote for the plan's symbol, so sizing and the risk check measure from the price a
        # market order would fill at now (they use the higher of it and the plan's entry).
        try:
            with open(os.path.join(BASE_DIR, "trader", "plan.json"), encoding="utf-8") as fh:
                psym = json.load(fh)["symbol"]
            q = engine.market_data.get(normalize_symbol(psym), {})
            if q.get("ltp") and q.get("quote_time"):
                t = datetime.utcfromtimestamp(q["quote_time"]).strftime("%Y-%m-%dT%H:%M:%SZ")
                with open(os.path.join(BASE_DIR, "trader", "prices.json"), "w", encoding="utf-8") as fh:
                    json.dump({"as_of": t, "source": "dashboard live quote", "prices": {psym: q["ltp"]},
                               "detail": {psym: {"time": t}}}, fh, indent=2)
        except (OSError, ValueError, KeyError):
            pass
        size = run_skill("trader-budget/size.py", ["--plan", "trader/plan.json", "--config", TRADER_CFG,
                                                  "--write", "trader/orders.json", "--json"])
        out = {"size": size, "risk": None, "ticket": None}
        if not size["data"] or not size["data"].get("orders"):
            return out
        out["risk"] = run_skill("trader-risk/check.py", ["--orders", "trader/orders.json", "--config", TRADER_CFG,
                                                        "--json"])
        out["ticket"] = run_skill("trader-broker/ticket.py", ["show", "--index", "1", "--json",
                                                             "--orders", "trader/orders.json", "--config", TRADER_CFG])
        return out


@app.post("/api/skills/place")
def skills_place(req: SkillPlace):
    """Record the user's yes for order 1 (the skill refuses anything but a plain yes), then send it."""
    with skills_lock:
        common = ["--index", "1", "--orders", "trader/orders.json", "--config", TRADER_CFG]
        approve = run_skill("trader-broker/ticket.py", ["approve", "--reply", req.reply] + common)
        if not approve["ok"]:
            return {"placed": False, "step": "approve", "message": approve["error"] or approve["text"]}
        send = run_skill("trader-broker/ticket.py", ["send"] + common)
        return {"placed": send["ok"], "step": "send", "message": send["error"] or send["text"]}


# --- Skills auto-trader: the same pipeline, on a timer, for the paper account only ---
# Every cycle it scans each enabled market for opening-range breakouts and runs every FRESH one
# through entry -> exit plan -> time machine -> size -> risk. It places a paper order only when
# all of these hold, and logs why every symbol was traded or skipped:
#   1. the breakout bar closed at most max_breakout_age_min ago (no chasing late entries)
#   2. the exit plan is accepted (charges under 50 % of the risk)
#   3. after charges, the replays' average R > 0 AND the rule's real history on this symbol
#      (at least min_history_trades trades) averages R > 0
#   4. trader-risk passes (per-trade and daily loss, trades a day, the entry window)
# One position per symbol, each symbol at most once a day, and skill trades are closed at flat-by.
from collections import deque
from datetime import timedelta, timezone

AUTO_DIR = os.path.join(BASE_DIR, "trader", "auto")          # its own plan / orders files
SHARED_STATE = os.path.join(BASE_DIR, "trader", "state", "broker.json")   # shared daily counters
AUTO_DEFAULTS = {"every_sec": 300, "stop": "or-low", "target": "2R", "max_breakout_age_min": 10,
                 "min_history_trades": 20}


class AutoTrader:
    """The Auto-Pilot's engine: on/off, market and SELECTED symbol come from the Auto-Pilot settings."""
    def __init__(self):
        self.log = deque(maxlen=200)
        self.traded = {}          # (market, day) -> symbols placed today
        self.last_cycle = {}      # market -> unix time of its last scan
        self.busy = False

    @property
    def enabled(self):
        return engine.auto_pilot

    @property
    def markets(self):
        return {"nse" if engine.autopilot_market == "NSE" else "crypto"}

    def note(self, market, symbol, action, detail):
        now = datetime.now()
        self.log.appendleft({"at": now.strftime("%Y-%m-%d %H:%M:%S"), "market": market,
                             "symbol": symbol, "action": action, "detail": detail})
        if action != "skip":   # the Auto-Pilot card shows the latest decision that did something
            engine.autopilot_status = {"symbol": normalize_symbol(symbol) if symbol else (market or "").upper(),
                                       "state": {"placed": "EXECUTING", "closed": "TAKING_PROFIT", "error": "ERROR",
                                                 "blocked": "BLOCKED"}.get(action, "SCANNING"),
                                       "message": "Skills: %s%s" % (symbol + " " if symbol else "", detail),
                                       "last_action": action.upper(), "last_action_time": now.strftime("%H:%M:%S")}


autotrader = AutoTrader()


def auto_cfg() -> dict:
    cfg = dict(AUTO_DEFAULTS)
    cfg.update((skills_config().get("auto") or {}))
    return cfg


def _local_now(market):
    """The market's own clock as a naive datetime: IST for NSE, UTC for crypto."""
    return datetime.utcnow() + (timedelta(hours=5, minutes=30) if market == "nse" else timedelta(0))


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def nse_window_open(now_ist) -> bool:
    """09:35-14:45 IST on a weekday while the NSE session is open (the risk check also blocks NSE holidays)."""
    t = now_ist.hour * 60 + now_ist.minute
    return now_ist.weekday() < 5 and 9 * 60 + 35 <= t <= 14 * 60 + 45 and engine.get_market_status()["nse"]["is_open"]


def auto_write_live_price(symbol: str):
    q = engine.market_data.get(normalize_symbol(symbol), {})
    if q.get("ltp") and q.get("quote_time"):
        t = datetime.utcfromtimestamp(q["quote_time"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(os.path.join(AUTO_DIR, "trader", "prices.json"), "w", encoding="utf-8") as fh:
            json.dump({"as_of": t, "source": "dashboard live quote", "prices": {symbol: q["ltp"]},
                       "detail": {symbol: {"time": t}}}, fh)


def auto_try_symbol(market: str, sym: str, cfg: dict) -> None:
    """One fresh breakout through the whole pipeline. Logs the outcome either way."""
    A = dict(cwd=AUTO_DIR)
    entry = run_skill("trader-entry/entry.py", ["check", sym, "--write", "trader/entry.json", "--json",
                                               "--config", TRADER_CFG], **A)
    e = entry["data"]
    if not e or e.get("status") != "triggered":
        autotrader.note(market, sym, "skip", "entry timer: %s" % ((e or {}).get("reason") or entry["error"]))
        return
    if (e.get("minutes_since") or 0) > cfg["max_breakout_age_min"]:
        autotrader.note(market, sym, "skip", "breakout %d min old (max %d)" % (e["minutes_since"], cfg["max_breakout_age_min"]))
        return
    plan = run_skill("trader-exit/exit.py", ["plan", "--from", "trader/entry.json", "--stop", cfg["stop"],
                                             "--target", cfg["target"], "--config", TRADER_CFG,
                                             "--write", "trader/plan.json", "--json"], **A)
    if not plan["ok"] or not plan["data"]:
        autotrader.note(market, sym, "skip", "exit plan refused: %s" % (plan["error"] or plan["text"]))
        return
    tm = run_skill("trader-timemachine/timemachine.py", ["run", "--plan", "trader/plan.json", "--until",
                                                        plan["data"]["flat_by"], "--json"], **A)
    if not tm["data"]:
        autotrader.note(market, sym, "skip", "time machine: %s" % (tm["error"] or tm["text"]))
        return
    mc, hist = tm["data"]["mc"], tm["data"].get("history") or {}
    odds = "replays %+.2fR, history %s trades %s after charges" % (
        mc["avg_R_net"], hist.get("triggered", 0),
        ("%+.2fR" % hist["avg_R_net"]) if hist.get("avg_R_net") is not None else "n/a")
    if mc["avg_R_net"] <= 0 or (hist.get("triggered") or 0) < cfg["min_history_trades"] or (hist.get("avg_R_net") or 0) <= 0:
        autotrader.note(market, sym, "skip", "no edge after charges (%s)" % odds)
        return
    q = engine.market_data.get(normalize_symbol(sym), {})
    if not q.get("ltp") or time_module.time() - q.get("quote_time", 0) > MAX_QUOTE_AGE.get(q.get("category"), 120.0):
        autotrader.note(market, sym, "skip", "edge OK (%s) but no live quote right now: not placed" % odds)
        return
    auto_write_live_price(sym)
    size = run_skill("trader-budget/size.py", ["--plan", "trader/plan.json", "--config", TRADER_CFG,
                                              "--write", "trader/orders.json", "--json"], **A)
    sd = size["data"] or {}
    if not sd.get("orders"):
        autotrader.note(market, sym, "skip", "sizing: %s" % ((sd.get("sizing") or {}).get("refusal") or size["error"]))
        return
    common = ["--orders", "trader/orders.json", "--config", TRADER_CFG, "--state", SHARED_STATE]
    with skills_lock:   # the shared daily counters: one risk check / placement at a time
        risk = run_skill("trader-risk/check.py", common + ["--json"], **A)
        rv = ((risk["data"] or {}).get("results") or [{}])[0]
        if rv.get("verdict") != "PASS":
            autotrader.note(market, sym, "blocked", "risk: %s" % "; ".join(rv.get("reasons") or [risk["error"] or "no verdict"]))
            return
        tk = ["--index", "1"] + common
        approve = run_skill("trader-broker/ticket.py", ["approve", "--reply", "yes (auto-trader, paper)"] + tk, **A)
        if not approve["ok"]:
            autotrader.note(market, sym, "error", "approve: %s" % (approve["error"] or approve["text"]))
            return
        send = run_skill("trader-broker/ticket.py", ["send"] + tk, **A)
    s = sd["sizing"]
    if send["ok"]:
        autotrader.traded.setdefault((market, _local_now(market).date().isoformat()), set()).add(sym)
        autotrader.note(market, sym, "placed", "bought %s at the live price, stop %s, target %s, max loss %s incl. "
                        "charges (%s)" % (s["qty"], s["stop"], s["target"], s["max_loss"], odds))
    else:
        autotrader.note(market, sym, "error", "send: %s" % (send["error"] or send["text"]))


def auto_cycle(market: str) -> None:
    cfg = auto_cfg()
    args = ["orb", "--market", market, "--json", "--quiet", "--no-write", "--config", TRADER_CFG]
    scan = run_skill("trader-scanner/scan.py", args, cwd=AUTO_DIR)
    d = scan["data"]
    if not d:
        autotrader.note(market, "", "scan", scan["error"] or scan["text"] or "no scan result")
        return
    now_min = _minutes(d["as_of"].split()[1])
    fresh = [h for h in d["hits"] if 0 <= now_min - _minutes(h["at"]) <= cfg["max_breakout_age_min"]]
    autotrader.note(market, "", "scan", "%s: %d breakouts today, %d fresh (<= %d min)"
                    % (d["as_of"], len(d["hits"]), len(fresh), cfg["max_breakout_age_min"]))
    day = _local_now(market).date().isoformat()
    done = autotrader.traded.get((market, day), set())
    if engine.autopilot_mode == "SELECTED":
        fresh = [h for h in fresh if normalize_symbol(h["symbol"]) == engine.autopilot_target_symbol]
    for h in fresh:
        sym = h["symbol"]
        pos = engine.positions.get(normalize_symbol(sym), {})
        if sym in done or pos.get("quantity", 0):
            autotrader.note(market, sym, "skip", "already traded today or already open")
            continue
        try:
            auto_try_symbol(market, sym, cfg)
        except Exception as ex:   # one bad symbol never stops the cycle
            autotrader.note(market, sym, "error", str(ex))


def auto_flat_by_exits() -> None:
    """Close skill-opened positions at the market's flat-by (NSE 15:10 IST, crypto 23:55 UTC)."""
    mk = skills_config().get("markets") or {}
    for sym, pos in list(engine.positions.items()):
        qty = pos.get("quantity", 0)
        if not qty:
            continue
        opening = next((o for o in engine.orders if o.get("symbol") == sym
                        and o.get("side") == ("BUY" if qty > 0 else "SELL")), None)
        if not opening or not str(opening.get("tag", "")).startswith("SKILL_"):
            continue
        market = "nse" if pos.get("category") == "NSE" else "crypto"
        flat = (mk.get(market) or {}).get("flat_by") or ("15:10" if market == "nse" else "23:55")
        now = _local_now(market)
        t = now.hour * 60 + now.minute
        if market == "nse":   # 15:10-15:30 IST; after the close the dashboard's own square-off takes over
            due = _minutes(flat) <= t <= 15 * 60 + 30
        else:                 # 23:55 UTC, or any crypto trade still open from an earlier UTC day
            try:
                opened = datetime.fromisoformat(opening["timestamp"]).astimezone(timezone.utc).date()
            except (KeyError, ValueError):
                opened = now.date()
            due = t >= _minutes(flat) or opened < now.date()
        if due:
            try:
                engine.place_order(OrderRequest(symbol=sym, side="SELL" if qty > 0 else "BUY", quantity=abs(qty),
                                                tag="SKILL_EXIT_FLAT_BY"))
                autotrader.note(market, sym, "closed", "flat by %s: closed %s at the live price" % (flat, abs(qty)))
            except HTTPException as ex:
                autotrader.note(market, sym, "error", "flat-by close failed: %s" % ex.detail)


def skills_autotrader_loop():
    os.makedirs(os.path.join(AUTO_DIR, "trader"), exist_ok=True)
    was_on = False
    while True:
        try:
            auto_flat_by_exits()
            if autotrader.enabled and not was_on:   # just switched on: scan right away
                autotrader.last_cycle = {}
                autotrader.note("", "", "on", "Auto-Pilot ON: trading skills on %s (paper account)"
                                % ", ".join(m.upper() for m in sorted(autotrader.markets)))
            elif was_on and not autotrader.enabled:
                autotrader.note("", "", "off", "Auto-Pilot OFF: no new trades; open skill trades still close at flat-by")
            was_on = autotrader.enabled
            if autotrader.enabled:
                cfg = auto_cfg()
                for market in sorted(autotrader.markets):
                    if time_module.time() - autotrader.last_cycle.get(market, 0) < cfg["every_sec"]:
                        continue
                    if market == "nse" and not nse_window_open(_local_now("nse")):
                        engine.autopilot_status = {"symbol": "NSE", "state": "MARKET_CLOSED", "last_action": "WAITING_OPEN",
                                                   "message": "Skills trade NSE 09:35-14:45 IST on weekdays; waiting.",
                                                   "last_action_time": datetime.now().strftime("%H:%M:%S")}
                        continue
                    autotrader.last_cycle[market] = time_module.time()
                    autotrader.busy = True
                    try:
                        auto_cycle(market)
                    finally:
                        autotrader.busy = False
        except Exception as ex:
            autotrader.note("", "", "error", "auto-trader: %s" % ex)
        time_module.sleep(20.0)


@app.get("/api/skills/auto")
def skills_auto_status():
    cfg = auto_cfg()
    return {"enabled": autotrader.enabled, "markets": sorted(autotrader.markets), "busy": autotrader.busy,
            "rules": cfg, "log": list(autotrader.log)[:60],
            "next_in": {m: max(0, int(cfg["every_sec"] - (time_module.time() - autotrader.last_cycle.get(m, 0))))
                        for m in autotrader.markets}}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    engine.subscribers.append(websocket)
    try:
        while True:
            with engine.lock:
                ticks_snapshot = {k: list(v) for k, v in engine.tick_history.items()}
                m_data = list(engine.market_data.values())
                indices_list = list(engine.indices_data.values())
                open_pos = [p for p in engine.positions.values() if p["quantity"] != 0]

            payload = {
                "market_status": engine.get_market_status(),
                "portfolio": engine.get_portfolio_summary(),
                "positions": open_pos,
                "market_data": m_data,
                "indices": indices_list,
                "tick_history": ticks_snapshot,
                "autopilot_status": engine.autopilot_status,
                "autopilot_target_symbol": engine.autopilot_target_symbol,
                "autopilot_mode": engine.autopilot_mode,
                "autopilot_speed": engine.autopilot_speed,
                "autopilot_risk": engine.autopilot_risk,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.5)  # Blazing fast 500ms real-time broadcast
    except WebSocketDisconnect:
        if websocket in engine.subscribers:
            engine.subscribers.remove(websocket)
    except Exception:
        if websocket in engine.subscribers:
            engine.subscribers.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001, reload=False)  # the app object: no second import
