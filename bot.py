"""
Indian Market Trading Agent - Main Terminal Controller
Run: python bot.py
"""

import sys
import os

from config import (
    INITIAL_CAPITAL,
    RISK_PER_TRADE_PCT,
    MAX_DAILY_LOSS_PCT,
    WATCHLIST,
    TRADING_MODE,
)
from screener import scan_watchlist
from backtester import run_portfolio_backtest


def print_banner():
    print("""
======================================================================
         INDIAN MARKET TRADING AGENT (NSE / BSE / MCX)
            Equipped with Risk Discipline & Execution Guardrails
======================================================================
  * Mode:            {mode}
  * Virtual Capital: Rs. {capital:,.2f}
  * Risk / Trade:    {risk_pct:.1f}% (Rs. {risk_val:,.2f})
  * Daily Circuit:   {circuit_pct:.1f}% Max Daily Loss (Rs. {circuit_val:,.2f})
======================================================================
""".format(
        mode=TRADING_MODE,
        capital=INITIAL_CAPITAL,
        risk_pct=RISK_PER_TRADE_PCT * 100,
        risk_val=INITIAL_CAPITAL * RISK_PER_TRADE_PCT,
        circuit_pct=MAX_DAILY_LOSS_PCT * 100,
        circuit_val=INITIAL_CAPITAL * MAX_DAILY_LOSS_PCT,
    ))


def run_position_calculator():
    print("\n--- Position Size & Risk Calculator ---")
    try:
        entry = float(input("Enter Expected Entry Price (Rs.): "))
        sl = float(input("Enter Stop Loss Price (Rs.): "))
        if entry <= 0 or sl <= 0 or entry == sl:
            print("Invalid price values.")
            return

        risk_budget = INITIAL_CAPITAL * RISK_PER_TRADE_PCT
        risk_per_share = abs(entry - sl)
        shares = max(1, int(risk_budget / risk_per_share))
        target_1_2 = round(entry + (2 * (entry - sl)) if entry > sl else entry - (2 * (sl - entry)), 2)

        print("\n[Safe Trade Allocation]")
        print(f"  * Recommended Quantity: {shares} shares")
        print(f"  * Total Position Value: Rs. {shares * entry:,.2f}")
        print(f"  * Risk Amount:          Rs. {shares * risk_per_share:,.2f} (Within Rs. {risk_budget:,.2f} budget)")
        print(f"  * 1:2 Target Price:     Rs. {target_1_2}")
    except ValueError:
        print("Please enter valid numbers.")


def run_totp_generator():
    print("\n--- Daily 2FA TOTP Generator for Indian Brokers ---")
    try:
        import pyotp
    except ImportError:
        print("pyotp is not installed. Run: pip install pyotp")
        return

    secret = input("Enter your broker Base32 TOTP Secret: ").strip()
    if secret:
        try:
            totp = pyotp.TOTP(secret.replace(" ", ""))
            code = totp.now()
            print(f"\nGenerated 6-digit TOTP Code: {code}")
            print("Valid for the next 30 seconds.")
        except Exception as e:
            print(f"Error generating TOTP: {e}")
    else:
        print("No secret provided.")


def run_paper_trading_demo():
    print("\n--- Running Live Paper Trading Simulation ---")
    sys.path.append(os.path.join(os.path.dirname(__file__), ".agents", "skills", "trader", "scripts"))
    from paper_engine import PaperBroker, OrderSide, OrderType

    broker = PaperBroker(initial_capital=INITIAL_CAPITAL, max_daily_loss_pct=MAX_DAILY_LOSS_PCT)
    print(f"Paper Broker initialized with Rs. {INITIAL_CAPITAL:,.2f}")

    # Simulated live trade execution
    print("\n[Step 1] Placing Simulated Market Buy Order on TCS...")
    order = broker.place_order(
        symbol="TCS",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        current_ltp=2475.0,
        tag="PAPER_DEMO"
    )
    print(f"  Order ID: {order.order_id} | Filled at: Rs. {order.filled_price:.2f}")

    print("\n[Step 2] Simulating Market Move (+1.5% Gain)...")
    broker.update_ltp("TCS", 2512.0)
    summary = broker.get_summary()
    print(f"  Unrealized PnL: Rs. {summary['unrealized_pnl']:+,.2f}")
    print(f"  Portfolio Value: Rs. {summary['portfolio_value']:,.2f}")

    print("\n[Step 3] Squaring off position at target...")
    broker.place_order(
        symbol="TCS",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=10,
        current_ltp=2512.0,
        tag="TARGET_HIT"
    )

    final_summary = broker.get_summary()
    print("\n=== Paper Session Final Performance ===")
    print(f"  Realized PnL:    Rs. {final_summary['realized_pnl']:+,.2f}")
    print(f"  Brokerage Paid:  Rs. {final_summary['total_trades'] * 20:.2f}")
    print(f"  Net Portfolio:   Rs. {final_summary['portfolio_value']:,.2f} ({final_summary['return_pct']:+.2f}%)")
    print(f"  Circuit Breaker: {'ACTIVE' if final_summary['circuit_breaker_active'] else 'NORMAL'}")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "dashboard":
            import webbrowser
            print("Opening live dashboard at http://127.0.0.1:8001 ...")
            webbrowser.open("http://127.0.0.1:8001")
            return
        elif cmd == "scan":
            scan_watchlist()
            return
        elif cmd == "backtest":
            run_portfolio_backtest()
            return
        elif cmd == "calc":
            run_position_calculator()
            return
        elif cmd == "paper":
            run_paper_trading_demo()
            return

    print_banner()
    print("Select an action:")
    print("  1. Launch Live Web Dashboard (http://127.0.0.1:8001)")
    print("  2. Scan Watchlist (Find active setups & risk sizes on NSE)")
    print("  3. Run Historical Backtest (Test strategy over past 1 year)")
    print("  4. Run Paper Trading Simulation Demo")
    print("  5. Position Size Calculator (Exact shares to buy)")
    print("  6. Generate Morning 2FA TOTP for Indian Broker")
    print("  7. Exit")

    choice = input("\nEnter choice [1-7]: ").strip()
    if choice == "1":
        import webbrowser
        print("Opening live trading dashboard in browser...")
        webbrowser.open("http://127.0.0.1:8001")
    elif choice == "2":
        scan_watchlist()
    elif choice == "3":
        run_portfolio_backtest()
    elif choice == "4":
        run_paper_trading_demo()
    elif choice == "5":
        run_position_calculator()
    elif choice == "6":
        run_totp_generator()
    elif choice == "7":
        print("Goodbye.")
    else:
        print("Invalid choice.")


if __name__ == "__main__":
    main()
