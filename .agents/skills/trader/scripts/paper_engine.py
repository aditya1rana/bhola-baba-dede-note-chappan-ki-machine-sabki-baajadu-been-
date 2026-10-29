"""
Paper Trading Engine for Indian Markets
Simulates broker order matching, position management, slippage, and RMS circuit breakers.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import uuid


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    filled_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    timestamp: datetime = field(default_factory=datetime.now)
    tag: str = ""


@dataclass
class Position:
    symbol: str
    quantity: int = 0  # positive for long, negative for short
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class PaperBroker:
    def __init__(
        self,
        initial_capital: float = 100000.0,  # ₹1 Lakh default
        slippage_pct: float = 0.0005,       # 0.05% realistic execution slippage
        brokerage_per_order: float = 20.0,   # Standard Indian discount broker fee
        max_daily_loss_pct: float = 0.02,   # 2% RMS Kill-Switch
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.slippage_pct = slippage_pct
        self.brokerage = brokerage_per_order
        self.max_daily_loss = initial_capital * max_daily_loss_pct

        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[dict] = []
        self.circuit_broken: bool = False

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        current_ltp: Optional[float] = None,
        tag: str = "",
    ) -> Order:
        """Place a paper order with RMS checks."""
        if self.circuit_broken:
            raise RuntimeError("RMS Circuit Breaker triggered: Max daily loss hit. Trading locked.")

        order_id = f"ORD_{uuid.uuid4().hex[:8].upper()}"
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
            tag=tag,
        )

        # Market order immediate fill simulation
        if order_type == OrderType.MARKET and current_ltp is not None:
            # Apply slippage
            slip = current_ltp * self.slippage_pct
            exec_price = current_ltp + slip if side == OrderSide.BUY else current_ltp - slip
            self._fill_order(order, exec_price)
        else:
            self.orders[order_id] = order

        return order

    def _fill_order(self, order: Order, fill_price: float):
        order.status = OrderStatus.FILLED
        order.filled_price = fill_price
        self.orders[order.order_id] = order

        # Deduct brokerage
        self.cash -= self.brokerage

        # Update position
        pos = self.positions.setdefault(order.symbol, Position(symbol=order.symbol))
        fill_qty = order.quantity if order.side == OrderSide.BUY else -order.quantity

        new_qty = pos.quantity + fill_qty

        if pos.quantity == 0:
            pos.avg_price = fill_price
            pos.quantity = new_qty
        elif (pos.quantity > 0 and fill_qty > 0) or (pos.quantity < 0 and fill_qty < 0):
            # Adding to existing position
            total_cost = (abs(pos.quantity) * pos.avg_price) + (abs(fill_qty) * fill_price)
            pos.quantity = new_qty
            pos.avg_price = total_cost / abs(new_qty)
        else:
            # Reducing or reversing position -> Realize PnL
            closed_qty = min(abs(pos.quantity), abs(fill_qty))
            pnl_per_share = (fill_price - pos.avg_price) if pos.quantity > 0 else (pos.avg_price - fill_price)
            realized = closed_qty * pnl_per_share
            pos.realized_pnl += realized
            self.cash += realized

            pos.quantity = new_qty
            if pos.quantity == 0:
                pos.avg_price = 0.0
            elif (pos.quantity > 0 and fill_qty > 0) or (pos.quantity < 0 and fill_qty < 0):
                pos.avg_price = fill_price

        self.trade_history.append({
            "timestamp": datetime.now().isoformat(),
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "price": fill_price,
            "tag": order.tag,
        })

    def update_ltp(self, symbol: str, current_ltp: float):
        """Update unrealized PnL and check RMS circuit breaker."""
        if symbol in self.positions:
            pos = self.positions[symbol]
            if pos.quantity > 0:
                pos.unrealized_pnl = (current_ltp - pos.avg_price) * pos.quantity
            elif pos.quantity < 0:
                pos.unrealized_pnl = (pos.avg_price - current_ltp) * abs(pos.quantity)
            else:
                pos.unrealized_pnl = 0.0

        # Check total daily loss
        total_pnl = sum(p.realized_pnl + p.unrealized_pnl for p in self.positions.values())
        if total_pnl <= -self.max_daily_loss:
            self.circuit_broken = True
            self.square_off_all(symbol_to_ltp={symbol: current_ltp})

    def square_off_all(self, symbol_to_ltp: Dict[str, float]):
        """Square off all open positions immediately (Intraday EOD or Circuit Breaker)."""
        for sym, pos in list(self.positions.items()):
            if pos.quantity != 0 and sym in symbol_to_ltp:
                side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
                qty = abs(pos.quantity)
                self.place_order(
                    symbol=sym,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=qty,
                    current_ltp=symbol_to_ltp[sym],
                    tag="SQUARE_OFF",
                )

    def get_summary(self) -> dict:
        total_realized = sum(p.realized_pnl for p in self.positions.values())
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        net_portfolio_value = self.cash + total_unrealized
        return {
            "initial_capital": self.initial_capital,
            "current_cash": round(self.cash, 2),
            "realized_pnl": round(total_realized, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "total_pnl": round(total_realized + total_unrealized, 2),
            "portfolio_value": round(net_portfolio_value, 2),
            "return_pct": round(((net_portfolio_value - self.initial_capital) / self.initial_capital) * 100, 2),
            "total_trades": len(self.trade_history),
            "circuit_breaker_active": self.circuit_broken,
        }
