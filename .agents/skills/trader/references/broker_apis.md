# Indian Broker APIs Quick Reference

A cheat sheet for configuring and authenticating with the top Indian broker APIs.

---

## 1. Angel One (SmartAPI) - Recommended (Free)

- **Official SDK:** `pip install smartapi-python`
- **Cost:** 100% Free
- **Auth Flow:**
  ```python
  from SmartApi import SmartConnect
  import pyotp

  api_key = "YOUR_API_KEY"
  client_code = "YOUR_CLIENT_ID"
  pin = "YOUR_4_DIGIT_PIN"
  totp_secret = "YOUR_TOTP_KEY"

  smart_api = SmartConnect(api_key)
  totp = pyotp.TOTP(totp_secret).now()
  data = smart_api.generateSession(client_code, pin, totp)
  auth_token = data['data']['jwtToken']
  feed_token = smart_api.getfeedToken()
  ```
- **Place Order (MIS / Intraday):**
  ```python
  order_params = {
      "variety": "NORMAL",
      "tradingsymbol": "RELIANCE-EQ",
      "symboltoken": "2885",
      "transactiontype": "BUY",
      "exchange": "NSE",
      "ordertype": "MARKET",
      "producttype": "INTRADAY",
      "duration": "DAY",
      "quantity": "10"
  }
  order_id = smart_api.placeOrder(order_params)
  ```

---

## 2. Dhan (DhanHQ) - Recommended (Free & Modern)

- **Official SDK:** `pip install dhanhq`
- **Cost:** 100% Free
- **Auth Flow:**
  - Dhan provides static long-lived Access Tokens via web portal (Settings > DhanHQ Developer APIs).
  ```python
  from dhanhq import dhanhq

  client_id = "YOUR_CLIENT_ID"
  access_token = "YOUR_ACCESS_TOKEN"
  dhan = dhanhq(client_id, access_token)

  # Check Fund Limits
  funds = dhan.get_fund_limits()
  ```
- **Place Order:**
  ```python
  response = dhan.place_order(
      security_id='1333', # HDFCBANK
      exchange_segment=dhan.NSE,
      transaction_type=dhan.BUY,
      quantity=5,
      order_type=dhan.MARKET,
      product_type=dhan.INTRA,
      price=0
  )
  ```

---

## 3. Zerodha (Kite Connect)

- **Official SDK:** `pip install kiteconnect`
- **Cost:** ₹2,000 / month (Trade API) + ₹2,000 / month (Historical data)
- **Auth Flow:**
  - Requires daily browser login or automated Playwright/Selenium flow to retrieve `request_token`.
  ```python
  from kiteconnect import KiteConnect

  kite = KiteConnect(api_key="YOUR_API_KEY")
  # Exchange request_token obtained from login redirect URL:
  data = kite.generate_session("REQUEST_TOKEN", api_secret="YOUR_API_SECRET")
  kite.set_access_token(data["access_token"])
  ```
- **Place Order:**
  ```python
  order_id = kite.place_order(
      variety=kite.VARIETY_REGULAR,
      exchange=kite.EXCHANGE_NSE,
      tradingsymbol="INFY",
      transaction_type=kite.TRANSACTION_TYPE_BUY,
      quantity=10,
      product=kite.PRODUCT_MIS,
      order_type=kite.ORDER_TYPE_MARKET
  )
  ```

---

## 4. Fyers (Fyers API v3)

- **Official SDK:** `pip install fyers-apiv3`
- **Cost:** Free
- **Auth Flow:**
  ```python
  from fyers_apiv3 import fyersModel

  client_id = "YOUR_APP_ID-100"
  secret_key = "YOUR_SECRET_KEY"
  access_token = "GENERATED_DAILY_TOKEN"

  fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path="")
  ```

---

## 5. Security & Credentials Management

Store credentials in `.env` (never commit to git):
```env
# Broker Selection: ANGEL_ONE | DHAN | ZERODHA | FYERS | PAPER
BROKER=PAPER
TRADING_MODE=PAPER

# Angel One
SMARTAPI_API_KEY=
SMARTAPI_CLIENT_ID=
SMARTAPI_PIN=
SMARTAPI_TOTP_SECRET=

# Dhan
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=

# Zerodha
KITE_API_KEY=
KITE_API_SECRET=

# RMS Settings
INITIAL_CAPITAL=100000
MAX_DAILY_LOSS_PCT=0.02
RISK_PER_TRADE_PCT=0.01
INTRADAY_SQUAREOFF_TIME=15:12
```
