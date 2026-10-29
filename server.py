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
USD_INR_RATE = 85.0         # Approximate conversion rate for USD assets
MAX_DAILY_LOSS_PCT = 0.40   # 40% Max daily drawdown circuit breaker
RISK_PER_TRADE_PCT = 0.01   # 1% risk per trade
BROKERAGE_PER_ORDER = 2.0   # ₹2 fair simulated brokerage per order
SLIPPAGE_PCT = 0.0002       # 0.02% realistic liquid crypto spread

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

    # --- Crypto Assets (24/7 Continuous Trading) ---
    "BTC": {"ticker": "BTC-USD", "name": "Bitcoin", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:BTCUSDT", "min_qty": 0.001, "step": 0.001},
    "ETH": {"ticker": "ETH-USD", "name": "Ethereum", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:ETHUSDT", "min_qty": 0.01, "step": 0.01},
    "SOL": {"ticker": "SOL-USD", "name": "Solana", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:SOLUSDT", "min_qty": 0.1, "step": 0.1},
    "DOGE": {"ticker": "DOGE-USD", "name": "Dogecoin", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:DOGEUSDT", "min_qty": 10.0, "step": 1.0},
    "BNB": {"ticker": "BNB-USD", "name": "Binance Coin", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:BNBUSDT", "min_qty": 0.05, "step": 0.05},
    "XRP": {"ticker": "XRP-USD", "name": "XRP Ripple", "category": "CRYPTO", "currency": "USD", "currency_symbol": "$", "tv": "BINANCE:XRPUSDT", "min_qty": 1.0, "step": 1.0}
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
    risk: Optional[str] = "HIGH"  # "HIGH" (Heavy allocation) or "NORMAL" (35% cash)

class AutoPilotToggle(BaseModel):
    enabled: bool


# --- Trading Engine State ---
class TradingEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.capital = INITIAL_CAPITAL
        self.cash = INITIAL_CAPITAL
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
        self.autopilot_risk = "HIGH"      # "HIGH" (Heavy allocation) or "NORMAL"
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
            self.trade_history.append(dict(row))

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

            ltp = self.market_data.get(clean_symbol, {}).get("ltp")

            if not ltp:
                try:
                    df = yf.download(ticker, period="1d", interval="1m", progress=False)
                    if not df.empty:
                        ltp = float(df['Close'].iloc[-1])
                    else:
                        ltp = 100.0
                except Exception:
                    ltp = 100.0

            order_id = f"ORD_{uuid.uuid4().hex[:8].upper()}"
            slip = ltp * SLIPPAGE_PCT
            fill_price = ltp + slip if req.side.upper() == "BUY" else ltp - slip
            fill_price = round(fill_price, 4 if meta["category"] == "CRYPTO" and ltp < 10 else 2)

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
                self.position_open_time[clean_symbol] = time_module.time()
            elif (old_qty > 0 and fill_qty > 0) or (old_qty < 0 and fill_qty < 0):
                total_cost = (abs(old_qty) * pos["avg_price"]) + (abs(fill_qty) * fill_price)
                pos["quantity"] = new_qty
                pos["avg_price"] = round(total_cost / abs(new_qty), 4 if meta["category"] == "CRYPTO" and fill_price < 10 else 2)
                if req.stop_loss: pos["stop_loss"] = req.stop_loss
                if req.target: pos["target"] = req.target
            else:
                # Closing or flipping
                closed_qty = min(abs(old_qty), abs(fill_qty))
                if old_qty > 0:
                    realized_delta = round((fill_price - pos["avg_price"]) * closed_qty, 2)
                else:
                    realized_delta = round((pos["avg_price"] - fill_price) * closed_qty, 2)

                pos["realized_pnl"] += realized_delta
                pos["quantity"] = new_qty
                if new_qty == 0:
                    pos["avg_price"] = 0.0
                    pos["stop_loss"] = None
                    pos["target"] = None
                    self.position_open_time.pop(clean_symbol, None)
                    self.last_exit_time[clean_symbol] = time_module.time()
                elif (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0):
                    pos["avg_price"] = fill_price
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
                    # Exit immediately
                    threading.Thread(
                        target=self.place_order,
                        args=(OrderRequest(symbol=clean_symbol, side=side, quantity=abs(qty), tag=tag),),
                        daemon=True
                    ).start()

    def get_portfolio_summary(self) -> dict:
        with self.lock:
            total_unrealized_inr = 0.0
            open_positions = 0
            for sym, pos in self.positions.items():
                if pos["quantity"] != 0:
                    open_positions += 1
                    rate = USD_INR_RATE if pos.get("currency") == "USD" else 1.0
                    total_unrealized_inr += (pos.get("unrealized_pnl", 0.0) * rate)

            total_realized_inr = sum(
                t["pnl"] * (USD_INR_RATE if t.get("currency") == "USD" else 1.0)
                for t in self.trade_history
            )
            total_pnl_inr = round(total_realized_inr + total_unrealized_inr, 2)
            portfolio_val_inr = round(self.capital + total_pnl_inr, 2)

            # Check Circuit Breaker (Expanded to 40% in HIGH RISK mode to allow big aggressive swings)
            loss_pct = 0.40 if self.autopilot_risk == "HIGH" else MAX_DAILY_LOSS_PCT
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
                "total_trades_count": len(self.trade_history),
                "max_daily_loss_limit": max_daily_loss,
                "max_daily_loss_pct": loss_pct * 100,
                "autopilot_risk": self.autopilot_risk,
                "circuit_breaker_active": self.circuit_broken,
                "usd_inr_rate": USD_INR_RATE
            }


# Singleton engine
engine = TradingEngine()


# --- Background Concurrent Market Poller ---
def fetch_crypto_data_binance() -> Dict[str, dict]:
    symbols_map = {
        "BTCUSDT": "BTC",
        "ETHUSDT": "ETH",
        "SOLUSDT": "SOL",
        "DOGEUSDT": "DOGE",
        "BNBUSDT": "BNB",
        "XRPUSDT": "XRP"
    }
    try:
        url = 'https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCUSDT%22%2C%22ETHUSDT%22%2C%22SOLUSDT%22%2C%22DOGEUSDT%22%2C%22BNBUSDT%22%2C%22XRPUSDT%22%5D'
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
            ltp = float(item["lastPrice"])
            prev_close = float(item.get("prevClosePrice", ltp))
            day_high = float(item.get("highPrice", ltp * 1.01))
            day_low = float(item.get("lowPrice", ltp * 0.99))
            vol = float(item.get("volume", 100000))
            change_pct = float(item.get("priceChangePercent", 0.0))

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
                "ltp": round(ltp, 4 if ltp < 10 else 2),
                "prev_close": round(prev_close, 2),
                "change_pct": round(change_pct, 2),
                "day_high": round(day_high, 2),
                "day_low": round(day_low, 2),
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
        ltp = float(info['lastPrice'])
        prev_close = float(info.get('regularMarketPreviousClose', ltp))
        day_high = float(info.get('dayHigh', ltp * 1.01))
        day_low = float(info.get('dayLow', ltp * 0.99))
        vol = int(info.get('lastVolume', 500000))
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
            "ltp": round(ltp, 4 if meta["category"] == "CRYPTO" and ltp < 10 else 2),
            "prev_close": round(prev_close, 2),
            "change_pct": change_pct,
            "day_high": round(day_high, 2),
            "day_low": round(day_low, 2),
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

                # Auto-Pilot Execution Logic
                if engine.auto_pilot and not engine.circuit_broken:
                    market_status = engine.get_market_status()
                    target_market = engine.autopilot_market or "CRYPTO"
                    cat = data.get("category", "")

                    # 1. STRICT SINGLE-MARKET ENFORCEMENT:
                    # Trade ONLY in the single chosen market (e.g. CRYPTO or US or NSE) - NEVER mixed!
                    if cat != target_market:
                        if target_market != "CRYPTO":
                            mkt_info = market_status.get(target_market.lower(), {})
                            is_open = mkt_info.get("is_open", False)
                            hours = mkt_info.get("hours", "")
                            status_str = "OPEN" if is_open else "CLOSED"
                            engine.autopilot_status = {
                                "symbol": target_market,
                                "state": "MARKET_FILTER",
                                "message": f"Auto-Pilot set to single market: {target_market} ({status_str}: {hours}). Crypto trades skipped.",
                                "last_action": "MARKET_FILTER",
                                "last_action_time": now_str
                            }
                        continue

                    # 2. STRICT GUARD: NEVER place trades on closed markets!
                    is_market_open = True
                    if cat == "NSE":
                        is_market_open = market_status["nse"]["is_open"]
                    elif cat == "CRYPTO":
                        is_market_open = True

                    if not is_market_open:
                        engine.autopilot_status = {
                            "symbol": target_market,
                            "state": "MARKET_CLOSED",
                            "message": f"{target_market} market is currently CLOSED. Auto-Pilot paused until market opens.",
                            "last_action": "WAITING_OPEN",
                            "last_action_time": now_str
                        }
                        continue  # Skip closed markets completely

                    # 3. Market Selection Guard
                    if engine.autopilot_mode == "SELECTED":
                        if sym != engine.autopilot_target_symbol:
                            continue  # Skip any asset that is not the user's selected target

                    with engine.lock:
                        open_crypto_positions = [
                            s for s, p in engine.positions.items()
                            if p.get("quantity", 0) != 0 and p.get("category") == "CRYPTO"
                        ]
                        open_crypto_count = len(open_crypto_positions)
                        pos = engine.positions.get(sym)
                        has_pos = (pos is not None and pos.get("quantity", 0) != 0)
                        available_cash = engine.cash

                    # 3. Position Management (Positive-Expectancy AlphaWave Trailing & Shield)
                    if has_pos:
                        qty = pos["quantity"]
                        avg_price = pos["avg_price"]
                        unrealized_pct = ((ltp - avg_price) / avg_price) * 100 * (1 if qty > 0 else -1) if avg_price else 0.0

                        # Track peak unrealized profit for dynamic trailing stop
                        if "max_profit_pct" not in pos:
                            pos["max_profit_pct"] = 0.0
                        pos["max_profit_pct"] = max(pos["max_profit_pct"], unrealized_pct)
                        peak_profit = pos["max_profit_pct"]

                        with engine.lock:
                            ticks = [t["price"] for t in engine.tick_history.get(sym, [])]

                        tick_diff = 0.0
                        if len(ticks) >= 2:
                            tick_diff = ticks[-1] - ticks[-2]

                        should_exit = False
                        exit_tag = "AUTOPILOT_TAKE_PROFIT"
                        exit_reason = ""

                        # Tier 1: Hard Stop-Loss (-0.50%): Cut failed setups strictly to preserve capital (1:2.5 R:R)
                        if unrealized_pct <= -0.50:
                            should_exit = True
                            exit_tag = "AUTOPILOT_STOP_LOSS"
                            exit_reason = f"Safety Stop-Loss triggered ({unrealized_pct:.2f}%)"

                        # Tier 2: Break-Even Shield: If peak touched >= +0.35%, protect capital!
                        # Exit if price pulls back to +0.08% (guarantees ₹4 brokerage is 100% paid + profit)
                        elif peak_profit >= 0.35 and unrealized_pct <= 0.08:
                            should_exit = True
                            exit_tag = "AUTOPILOT_BREAK_EVEN"
                            exit_reason = f"Break-Even Shield locked (+{unrealized_pct:.2f}% | peak was +{peak_profit:.2f}%)"

                        # Tier 3: Trailing Profit Runner:
                        # If peak reached >= +0.60%, trail behind peak by 0.25% to let big winners run!
                        elif peak_profit >= 0.60 and unrealized_pct <= (peak_profit - 0.25):
                            should_exit = True
                            exit_tag = "AUTOPILOT_TRAILING_PROFIT"
                            exit_reason = f"Trailing Profit Banked (+{unrealized_pct:.2f}% | peak was +{peak_profit:.2f}%)"

                        # Tier 4: Major Profit Target (+1.25% or higher): Bank full target objective!
                        elif unrealized_pct >= 1.25:
                            should_exit = True
                            exit_tag = "AUTOPILOT_TARGET_HIT"
                            exit_reason = f"Full Profit Target Reached (+{unrealized_pct:.2f}%)"

                        if should_exit:
                            side = "SELL" if qty > 0 else "BUY"
                            engine.autopilot_status = {
                                "symbol": sym,
                                "state": "TAKING_PROFIT" if unrealized_pct > 0 else "STOP_LOSS",
                                "message": f"Auto-Pilot [{sym}]: {exit_reason}",
                                "last_action": f"{exit_tag}_{side}",
                                "last_action_time": now_str
                            }
                            try:
                                engine.place_order(OrderRequest(
                                    symbol=sym,
                                    side=side,
                                    quantity=abs(qty),
                                    tag=exit_tag
                                ))
                            except Exception as e:
                                print(f"[AutoPilot Exit Error] {e}")
                            continue
                        else:
                            c_sym = data.get("currency_symbol", "$")
                            tick_dir = "+UP" if tick_diff > 0 else ("-DOWN" if tick_diff < 0 else "=FLAT")
                            engine.autopilot_status = {
                                "symbol": sym,
                                "state": "HOLDING_POSITION",
                                "message": f"Holding {abs(qty)} {sym} @ {c_sym}{avg_price} ({unrealized_pct:+.2f}% | Peak: +{peak_profit:.2f}% | Tick: {tick_dir} {abs(tick_diff):.2f})",
                                "last_action": "MONITORING",
                                "last_action_time": now_str
                            }
                            continue

                    # 4. Entry Signal Evaluation (Anti-Churn & Positive Expectancy Filter)
                    if not has_pos:
                        # Anti-Churn Cooldown: Require at least 25 seconds after last exit on this coin
                        last_exit = engine.last_exit_time.get(sym, 0.0)
                        if (time_module.time() - last_exit) < 25.0:
                            continue

                        # In MULTI mode, cap max concurrent open crypto positions to 4
                        if engine.autopilot_mode == "MULTI" and open_crypto_count >= 4:
                            continue

                        # Minimum margin check
                        min_margin = 8000.0 if engine.autopilot_mode == "MULTI" else 15000.0
                        if available_cash < min_margin:
                            engine.autopilot_status = {
                                "symbol": sym,
                                "state": "LOW_MARGIN",
                                "message": f"Available cash (Rs.{available_cash:.2f}) too low for new positions.",
                                "last_action": "WAITING_MARGIN",
                                "last_action_time": now_str
                            }
                            continue

                        should_trade = False
                        trade_side = "BUY"
                        trade_tag = f"AUTOPILOT_{cat}"
                        reason = ""

                        with engine.lock:
                            ticks = [t["price"] for t in engine.tick_history.get(sym, [])]

                        if cat == "CRYPTO":
                            # High-Probability Quant Momentum & Volatility Breakout Filter:
                            if len(ticks) >= 10:
                                fast_ema = calc_ema(ticks, 5)
                                slow_ema = calc_ema(ticks, 15)
                                recent_high = max(ticks[-15:])
                                recent_low = min(ticks[-15:])
                                rng = max(0.0001, recent_high - recent_low)
                                pos_in_range = (ltp - recent_low) / rng

                                chg = data.get("change_pct", 0.0)
                                day_high = data.get("day_high", ltp * 1.01)
                                day_low = data.get("day_low", ltp * 0.99)

                                # Bullish Momentum Breakout
                                if fast_ema > slow_ema and pos_in_range >= 0.65 and chg > -2.0 and ltp > (day_low * 1.002):
                                    should_trade = True
                                    trade_side = "BUY"
                                    trade_tag = "AUTOPILOT_QUANT_BREAKOUT"
                                    reason = f"Bullish EMA Breakout (Range: {pos_in_range*100:.0f}%, 24h: {chg:+.1f}%)"
                                # Bearish Momentum Breakdown
                                elif fast_ema < slow_ema and pos_in_range <= 0.35 and chg < 2.0 and ltp < (day_high * 0.998):
                                    should_trade = True
                                    trade_side = "SELL"
                                    trade_tag = "AUTOPILOT_QUANT_BREAKDOWN"
                                    reason = f"Bearish EMA Breakdown (Range: {pos_in_range*100:.0f}%, 24h: {chg:+.1f}%)"

                        elif data["is_breakout"] or data["is_vcp"]:
                            should_trade = True
                            trade_side = "BUY"
                            trade_tag = "AUTOPILOT_BREAKOUT"
                            reason = "VCP volatility breakout"
                        elif data["trend"] == "STRONG UPTREND":
                            should_trade = True
                            trade_side = "BUY"
                            trade_tag = f"AUTOPILOT_{cat}_TREND"
                            reason = "Active session trend momentum"

                        if should_trade:
                            # Sizing calibrated for Rs.5,000+ daily goal:
                            # Deploy ~$180 to $225 USD (~Rs.15,000 - Rs.19,000 INR) per position
                            if data.get("currency") == "USD":
                                if engine.autopilot_risk == "HIGH":
                                    native_alloc = 200.0 if engine.autopilot_mode == "MULTI" else 250.0  # ~$200 - $250 USD per trade
                                else:
                                    native_alloc = 125.0 if engine.autopilot_mode == "MULTI" else 175.0  # ~$125 - $175 USD per trade
                                max_alloc_inr = native_alloc * USD_INR_RATE
                            else:
                                if engine.autopilot_risk == "HIGH":
                                    max_alloc_inr = 17000.0 if engine.autopilot_mode == "MULTI" else 25000.0
                                else:
                                    max_alloc_inr = 10000.0 if engine.autopilot_mode == "MULTI" else 15000.0
                                native_alloc = max_alloc_inr

                            # Margin headroom check: leave at least Rs.10,000 cash buffer
                            if max_alloc_inr > (available_cash - 5000.0):
                                max_alloc_inr = max(2000.0, available_cash - 5000.0)
                                if data.get("currency") == "USD":
                                    native_alloc = max_alloc_inr / USD_INR_RATE

                            meta = ASSETS.get(sym, {})
                            min_qty = meta.get("min_qty", 0.001 if cat == "CRYPTO" else 1.0)

                            if cat == "CRYPTO":
                                auto_qty = max(min_qty, round(native_alloc / ltp, 4 if ltp < 1000 else 4))
                            else:
                                auto_qty = max(min_qty, round(native_alloc / ltp, 0))

                            sl_mult = 0.995 if trade_side == "BUY" else 1.005
                            tgt_mult = 1.0125 if trade_side == "BUY" else 0.9875
                            sl_price = round(ltp * sl_mult, 4 if ltp < 10 else 2)
                            tgt_price = round(ltp * tgt_mult, 4 if ltp < 10 else 2)

                            alloc_str = f"${native_alloc:.0f} USD (Rs.{max_alloc_inr:,.0f})" if data.get("currency") == "USD" else f"Rs.{max_alloc_inr:,.0f}"
                            engine.autopilot_status = {
                                "symbol": sym,
                                "state": "EXECUTING",
                                "message": f"🔥 [{sym}] {trade_side} {auto_qty} {sym} [{alloc_str}] ({reason})",
                                "last_action": f"ENTER_{trade_side}",
                                "last_action_time": now_str
                            }

                            try:
                                req = OrderRequest(
                                    symbol=sym,
                                    side=trade_side,
                                    quantity=auto_qty,
                                    stop_loss=sl_price,
                                    target=tgt_price,
                                    tag=trade_tag
                                )
                                engine.place_order(req)
                            except Exception as e:
                                print(f"[AutoPilot Order Error] {e}")
        except Exception as e:
            print(f"[Market Poller Error] {e}")

        time_module.sleep(1.0)  # Fast 1.0s concurrent tick cycle


# Start poller threads
poller_thread = threading.Thread(target=background_market_poller, daemon=True)
poller_thread.start()

equity_thread = threading.Thread(target=background_equity_poller, daemon=True)
equity_thread.start()


# --- FastAPI App ---
app = FastAPI(title="Multi-Market Algorithmic Trading Terminal", version="2.0.0")

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
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

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
    uvicorn.run("server:app", host="127.0.0.1", port=8001, reload=False)
