# Indian Market Algorithmic Trading Agent

An automated trading agent and quantitative workbench tailored for the **National Stock Exchange (NSE)**, featuring Mark Minervini Volatility Contraction Pattern (VCP) detection, Opening Range Breakout (ORB), risk management guardrails, and paper trading execution.

---

## Quick Start: How to Run

### 1. Launch Live Web Dashboard (Recommended)
Open your browser at:
👉 **[http://127.0.0.1:8001](http://127.0.0.1:8001)**

Or from terminal:
```bash
python bot.py dashboard
```

### 2. Command-Line Options
```bash
# Interactive Menu
python bot.py

# Directly scan the market for active setups & risk sizing
python bot.py scan

# Test strategy over past 1 year of historical NSE data
python bot.py backtest

# Run a simulated paper trading session
python bot.py paper
```

---

## Project Structure

- [`bot.py`](file:///c:/codes/trade/bot.py): Main terminal control center and interactive launcher.
- [`config.py`](file:///c:/codes/trade/config.py): Settings for account capital, risk limits, watchlist, and broker credentials.
- [`screener.py`](file:///c:/codes/trade/screener.py): Scans NSE stocks, detects Trend (EMA 20/50), RSI, VCP consolidations, and computes exact share quantities.
- [`backtester.py`](file:///c:/codes/trade/backtester.py): Backtesting engine with realistic round-trip brokerage and ATR risk controls.
- [`.agents/skills/trader/`](file:///c:/codes/trade/.agents/skills/trader/SKILL.md): Core execution skill with `paper_engine.py`, `indicators.py`, and `totp_helper.py`.
- [`.agents/skills/`](file:///c:/codes/trade/.agents/skills/): Integrated analytical skills (`vcp-screener`, `position-sizer`, `drawdown-circuit-breaker`, `backtest-expert`, etc.).

---

## Risk Management Guardrails (Built-in)

1. **Max Daily Loss Limit (2% / ₹2,000):** If daily losses hit ₹2,000, the circuit breaker automatically halts order placement.
2. **Fixed Risk Per Trade (1% / ₹1,000):** Position size is mathematically calculated so that if a stop-loss is triggered, the loss is capped at ₹1,000.
3. **Paper Trading First:** All orders execute in simulated mode by default until you choose to connect a live broker.
