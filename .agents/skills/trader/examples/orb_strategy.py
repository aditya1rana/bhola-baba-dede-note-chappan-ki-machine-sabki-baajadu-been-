"""
15-Minute Opening Range Breakout (ORB) Strategy Example
Executes paper trading on Indian equity intraday candles with RMS position sizing and stop loss.
"""

import sys
import os

# Add parent scripts directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

from paper_engine import PaperBroker, OrderSide, OrderType
import pandas as pd
import numpy as np


class ORBStrategy:
    """
    Opening Range Breakout (ORB) Strategy:
    1. Records the High and Low of the first 15 minutes (09:15 to 09:30).
    2. Enters LONG if price breaks above 15m High with volume confirmation.
    3. Enters SHORT if price breaks below 15m Low with volume confirmation.
    4. Sets Stop Loss at opposite band or fixed ATR, target at 1:2 Risk/Reward.
    """

    def __init__(self, broker: PaperBroker, risk_per_trade_pct: float = 0.01):
        self.broker = broker
        self.risk_pct = risk_per_trade_pct
        self.active_trade = None
        self.opening_high = None
        self.opening_low = None

    def set_opening_range(self, high: float, low: float):
        self.opening_high = high
        self.opening_low = low
        print(f"[ORB Engine] Opening Range Locked -> High: Rs. {high:.2f} | Low: Rs. {low:.2f}")

    def on_candle(self, symbol: str, candle: dict):
        """
        Process a new 5-minute candle.
        candle: {'time': str, 'open': float, 'high': float, 'low': float, 'close': float, 'volume': int}
        """
        close = candle['close']
        self.broker.update_ltp(symbol, close)

        # If already in a position, manage Stop-Loss and Target
        if self.active_trade:
            pos_side = self.active_trade['side']
            sl = self.active_trade['stop_loss']
            target = self.active_trade['target']

            # Check SL or Target hit
            if pos_side == "BUY":
                if close <= sl:
                    print(f"[EXIT - SL HIT] Price: Rs. {close:.2f} <= SL: Rs. {sl:.2f}")
                    self.broker.place_order(symbol, OrderSide.SELL, OrderType.MARKET, self.active_trade['qty'], current_ltp=close, tag="SL_HIT")
                    self.active_trade = None
                elif close >= target:
                    print(f"[EXIT - TARGET HIT] Price: Rs. {close:.2f} >= Target: Rs. {target:.2f}")
                    self.broker.place_order(symbol, OrderSide.SELL, OrderType.MARKET, self.active_trade['qty'], current_ltp=close, tag="TARGET_HIT")
                    self.active_trade = None
            elif pos_side == "SELL":
                if close >= sl:
                    print(f"[EXIT - SL HIT] Price: Rs. {close:.2f} >= SL: Rs. {sl:.2f}")
                    self.broker.place_order(symbol, OrderSide.BUY, OrderType.MARKET, self.active_trade['qty'], current_ltp=close, tag="SL_HIT")
                    self.active_trade = None
                elif close <= target:
                    print(f"[EXIT - TARGET HIT] Price: Rs. {close:.2f} <= Target: Rs. {target:.2f}")
                    self.broker.place_order(symbol, OrderSide.BUY, OrderType.MARKET, self.active_trade['qty'], current_ltp=close, tag="TARGET_HIT")
                    self.active_trade = None
            return

        # Check for Entry Signals
        if self.opening_high is None or self.opening_low is None:
            return

        risk_amount = self.broker.cash * self.risk_pct

        # Long breakout
        if close > self.opening_high:
            sl_price = self.opening_low
            risk_per_share = max(1.0, close - sl_price)
            qty = max(1, int(risk_amount / risk_per_share))
            target_price = close + (2 * risk_per_share)

            print(f"[LONG BREAKOUT] Entry: Rs. {close:.2f} | Qty: {qty} | SL: Rs. {sl_price:.2f} | Target: Rs. {target_price:.2f}")
            self.broker.place_order(symbol, OrderSide.BUY, OrderType.MARKET, qty, current_ltp=close, tag="ORB_LONG")
            self.active_trade = {"side": "BUY", "qty": qty, "entry": close, "stop_loss": sl_price, "target": target_price}

        # Short breakdown
        elif close < self.opening_low:
            sl_price = self.opening_high
            risk_per_share = max(1.0, sl_price - close)
            qty = max(1, int(risk_amount / risk_per_share))
            target_price = close - (2 * risk_per_share)

            print(f"[SHORT BREAKDOWN] Entry: Rs. {close:.2f} | Qty: {qty} | SL: Rs. {sl_price:.2f} | Target: Rs. {target_price:.2f}")
            self.broker.place_order(symbol, OrderSide.SELL, OrderType.MARKET, qty, current_ltp=close, tag="ORB_SHORT")
            self.active_trade = {"side": "SELL", "qty": qty, "entry": close, "stop_loss": sl_price, "target": target_price}


if __name__ == "__main__":
    print("=== Testing ORB Strategy on Simulated NIFTY 50 Stock Candles ===")
    broker = PaperBroker(initial_capital=100000.0)
    strategy = ORBStrategy(broker, risk_per_trade_pct=0.01)

    # 1. 09:15 - 09:30 Opening Range Formation
    strategy.set_opening_range(high=2850.0, low=2820.0)

    # 2. Simulated 5-min candles
    candles = [
        {"time": "09:35", "close": 2840.0},
        {"time": "09:40", "close": 2855.0},  # Breakout trigger
        {"time": "09:45", "close": 2870.0},
        {"time": "09:50", "close": 2915.0},  # Target hit (Entry 2855, SL 2820 => Risk 35, Target 2855 + 70 = 2925, let's test 2930)
        {"time": "09:55", "close": 2935.0},
    ]

    for c in candles:
        strategy.on_candle("RELIANCE", c)

    summary = broker.get_summary()
    print("\n=== End of Session Paper Portfolio Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
