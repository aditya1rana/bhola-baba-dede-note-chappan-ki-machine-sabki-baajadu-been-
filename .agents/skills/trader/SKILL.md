---
name: trader
description: Quantitative trading and algorithmic execution skill specializing in Indian financial markets (NSE, BSE, MCX) and multi-broker automation. Covers broker integrations (Zerodha Kite, Angel One SmartAPI, DhanHQ, Fyers), 2FA/TOTP authentication, market data streaming, technical indicators, backtesting, paper trading simulation, and SEBI-compliant risk management guardrails.
---

# Quantitative & Algorithmic Trading Skill (Indian Markets & Beyond)

This skill provides domain expertise, implementation patterns, and execution safeguards for building, backtesting, and running algorithmic trading agents for Indian financial markets (NSE/BSE/MCX) and global markets.

---

## 1. Indian Market Fundamentals & Timings

### Trading Sessions (IST - UTC+5:30)
- **Pre-Market Session:** 09:00 AM – 09:08 AM (Order collection and price discovery)
- **Regular Trading Hours:** 09:15 AM – 03:30 PM
  - *Morning Momentum Window:* 09:15 AM – 10:30 AM (Highest volatility & liquidity)
  - *Mid-Day Lull:* 11:30 AM – 01:30 PM (Range-bound consolidation)
  - *European Open & Closing Wave:* 01:30 PM – 03:15 PM (Trend continuation or reversals)
- **MIS / Intraday Auto Square-Off:** 03:15 PM – 03:20 PM (Brokers automatically square off intraday positions with penalty fees; bots must square off by 03:12–03:14 PM).
- **Post-Market Session:** 03:40 PM – 04:00 PM

### Product Codes & Segment Types
- **MIS (Margin Intraday Square-off):** Intraday positions with leverage, auto squared-off before market close.
- **CNC (Cash and Carry):** 100% upfront equity delivery (zero leverage, held in Demat).
- **NRML (Normal):** Overnight derivatives (Futures & Options) held till expiry.
- **Order Varieties:** `MARKET`, `LIMIT`, `SL` (Stop-loss limit), `SL-M` (Stop-loss market - largely phased out for options by exchanges to prevent freak trades).

---

## 2. Broker Integrations & Daily 2FA Flow

Under SEBI regulations, API access requires daily Two-Factor Authentication (2FA) with a Time-based One-Time Password (TOTP).

### Supported Brokers Overview

| Broker | Python SDK | Daily Cost | Rate Limit | Key Strength |
| :--- | :--- | :--- | :--- | :--- |
| **Angel One** | `smartapi-python` | Free | 3 req/sec | Completely free API, easy TOTP integration |
| **Dhan** | `dhanhq` | Free | 5 req/sec | Designed for quants/super-traders, fast execution |
| **Fyers** | `fyers-apiv3` | Free | 10 req/sec | Free tick data & WebSocket, good developer portal |
| **Zerodha** | `kiteconnect` | ₹2,000/mo | 10 req/sec | Industry standard, rock solid stability |

### Automated Morning 2FA Token Generation Pattern
```python
import pyotp
import requests

def generate_totp(totp_secret: str) -> str:
    """Generate 6-digit TOTP for SEBI mandatory 2FA daily login."""
    totp = pyotp.TOTP(totp_secret)
    return totp.now()
```

---

## 3. Mandatory Risk Management System (RMS) Guardrails

Every trading bot **must strictly follow these rules** before sending any order to a broker:

1. **Max Daily Loss Limit (Kill-Switch):**
   - If accumulated daily loss reaches the configured threshold (e.g., 2% of total account capital or a fixed ₹ amount), the bot MUST:
     1. Immediately cancel all pending/unfilled orders.
     2. Market square-off all open positions.
     3. Lock execution and terminate for the day.
2. **Fixed Fractional Position Sizing:**
   - Never risk more than 1% to 2% of total capital on a single trade.
   - Quantity Formula:
     $$\text{Quantity} = \left\lfloor \frac{\text{Capital} \times \text{Risk \%}}{|\text{Entry Price} - \text{Stop Loss Price}|} \right\rfloor$$
3. **Hard Stop-Loss Requirement:**
   - Every entry order MUST be immediately paired with a Stop-Loss order or a synthetic monitored exit.
4. **Intraday Square-Off Circuit (03:12 PM IST):**
   - For all intraday/MIS strategies, initiate graceful liquidation at 03:12 PM IST to avoid exchange/broker auto-square-off charges (~₹50 + GST per order).
5. **Circuit Breaker on Repeated Errors:**
   - If 3 consecutive order rejections occur (insufficient margin, invalid token, etc.), halt trading and notify the operator via Telegram/Discord.

---

## 4. Standard Project Workflow

Always follow this 3-stage validation cycle:

```
[Historical Backtest] ──► [Paper Trading (Simulated Execution)] ──► [Live Deployment (Micro-lot)]
```

### Stage 1: Backtesting
- Use historical tick/candle data (1-min, 5-min, 15-min).
- Deduct realistic transaction costs (Brokerage ₹20/order, STT, Exchange transaction charges, Stamp duty, GST, and estimated slippage of 0.05% - 0.1%).
- Metrics to evaluate: Sharpe Ratio (> 1.5), Profit Factor (> 1.4), Max Drawdown (< 10%), Win Rate (typically 40%-60% for trend strategies with R:R > 1:2).

### Stage 2: Paper Trading (Forward Testing)
- Run with live WebSocket or poll-based tick data during market hours (09:15 - 15:30 IST).
- Emulate the broker order book, position management, and PnL tracking in memory or SQLite.
- Verify that signal generation, fill logic, stop losses, and notifications trigger as expected without financial risk.

### Stage 3: Live Micro-Execution
- Start with 1 equity share or 1 option lot.
- Validate API latency, slippage, and broker reconciliation.

---

## 5. Core Strategies for Indian Markets

1. **15-Min Opening Range Breakout (ORB):**
   - Mark the High and Low of the first 15 minutes (09:15 to 09:30 IST).
   - Enter LONG on 5-min candle close above the 15-min High.
   - Enter SHORT on 5-min candle close below the 15-min Low.
   - SL at 0.5% or VWAP; Target at 1:2 Risk-to-Reward.
2. **VWAP + EMA Pullback (Intraday Trend Following):**
   - Trend Filter: Price > VWAP and 20 EMA > 50 EMA.
   - Trigger: Pullback touch to 20 EMA with bullish rejection candle.
3. **9:20 AM Short Straddle / Strangle (Index Options - Nifty / Bank Nifty):**
   - At 09:20 AM IST, sell ATM Call and ATM Put.
   - Set individual Stop-Loss of 25%–30% on each option leg.
   - Square off at 03:05 PM IST.
   - Benefit from intraday theta decay (time decay).

---

## 6. Helper Utilities in this Skill

- `scripts/paper_engine.py`: Self-contained simulated broker supporting market, limit, SL, and PnL reporting.
- `scripts/indicators.py`: Vectorized technical indicators (VWAP, Supertrend, EMA, RSI, ATR, Bollinger Bands).
- `scripts/totp_helper.py`: Automated 2FA TOTP code generator for Indian broker APIs.
- `examples/orb_strategy.py`: Ready-to-run ORB strategy implementation for Nifty 50 stocks with live paper trading.
