
import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from datetime import datetime

# ================= CONFIG ==================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJwX2lwIjoiIiwic19pcCI6IiIsImlzcyI6ImRoYW4iLCJwYXJ0bmVySWQiOiIiLCJleHAiOjE3NjYzNDc3ODYsImlhdCI6MTc2NjI2MTM4NiwidG9rZW5Db25zdW1lclR5cGUiOiJTRUxGIiwid2ViaG9va1VybCI6Imh0dHBzOi8vbG9jYWxob3N0IiwiZGhhbkNsaWVudElkIjoiMTEwMjcxMjM4MCJ9.uQ4LyVOZqiy1ZyIENwcBT0Eei8taXbR8KgNW40NV0Y3nR_AQsmAC3JtZSoFE5p2xBwwB3q6ko_JEGTe7x_2ZTA"


API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I", "security_id": 256265},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I", "security_id": 260105}
}

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# =============== STREAMLIT SETUP ===============
st.set_page_config(layout="wide")
st_autorefresh(interval=30_000, key="refresh")
st.title("📊 NIFTY / BANKNIFTY Option Chain – Live Price + Highlight")

# ======== MARKET PRICE FUNCTION ==========
@st.cache_data(ttl=10)
def fetch_market_quote(security_id):
    """
    Use the Market Quote API to fetch LTP and previous close.
    """
    url = f"{API_BASE}/marketfeed/ltp"
    payload = {
        # NSE_FNO is used for F&O instruments; index security IDs go here
        "NSE_FNO": [security_id]
    }
    r = requests.post(url, headers=HEADERS, json=payload)

    if r.status_code != 200:
        return None, None

    data = r.json().get("data", {})
    if not data:
        return None, None

    # The API returns a structure keyed by security id
    quote_info = data.get(str(security_id), {})
    # The exact LTP field may vary; check "ltp" or similar
    ltp = quote_info.get("ltp") or quote_info.get("last_price")
    prev_close = quote_info.get("previous_close") or quote_info.get("prev_close")
    return ltp, prev_close

# ======== SELECT SYMBOL ========
symbol = st.selectbox("Select Index", list(UNDERLYINGS.keys()))
cfg = UNDERLYINGS[symbol]

# ======== FETCH LIVE PRICE ========
live_price, prev_close = fetch_market_quote(cfg["security_id"])

if live_price is not None:
    pct_change = ((live_price - prev_close) / prev_close * 100) if prev_close else None
else:
    pct_change = None

col1, col2, col3 = st.columns(3)
col1.metric("Current Price", f"{live_price:.2f}" if live_price else "N/A")
col2.metric("Previous Close", f"{prev_close:.2f}" if prev_close else "N/A")
col3.metric("% Change", f"{pct_change:.2f}%" if pct_change else "N/A")

# ======== FETCH OPTION CHAIN ========
# Expiry list
r_exp = requests.post(
    f"{API_BASE}/optionchain/expirylist",
    headers=HEADERS,
    json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"]}
)
expiries = r_exp.json().get("data", []) if r_exp.status_code == 200 else []
if not expiries:
    st.warning("No option expiries available")
    st.stop()

expiry = expiries[0]  # nearest expiry

r_oc = requests.post(
    f"{API_BASE}/optionchain",
    headers=HEADERS,
    json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"], "Expiry": expiry}
)

if r_oc.status_code != 200:
    st.warning("Option chain not available")
    st.stop()

oc_data = r_oc.json().get("data", {}).get("oc", {})
if not oc_data:
    st.warning("No option chain data")
    st.stop()

# ======== BUILD TABLE ===========
strikes = sorted(float(k) for k in oc_data.keys())

# Center around live price if available
if live_price is not None:
    center = min(strikes, key=lambda x: abs(x - live_price))
else:
    center = strikes[len(strikes) // 2]

idx = strikes.index(center)
selected_strikes = strikes[max(0, idx - 20): idx + 21]

rows = []
for strike in selected_strikes:
    s = oc_data.get(f"{strike:.6f}", {})
    ce = s.get("ce", {})
    pe = s.get("pe", {})
    rows.append({
        "Strike": strike,
        "CE LTP": ce.get("last_price"),
        "CE OI": ce.get("oi"),
        "CE IV": ce.get("implied_volatility"),
        "CE Delta": ce.get("greeks", {}).get("delta"),
        "PE LTP": pe.get("last_price"),
        "PE OI": pe.get("oi"),
        "PE IV": pe.get("implied_volatility"),
        "PE Delta": pe.get("greeks", {}).get("delta"),
    })

df = pd.DataFrame(rows)

highlight_strikes = []
if live_price is not None:
    lower = max([s for s in df["Strike"] if s <= live_price], default=None)
    upper = min([s for s in df["Strike"] if s >= live_price], default=None)
    highlight_strikes = [lower, upper]

def highlight_rows(r):
    if r["Strike"] in highlight_strikes:
        return ["background-color:#003366;color:white"] * len(r)
    return [""] * len(r)

styled = df.style.apply(highlight_rows, axis=1)

st.subheader(f"{symbol} Option Chain (Expiry {expiry})")
st.dataframe(styled, use_container_width=True)

st.caption(f"⏱ Auto-refresh 30s | Updated at {datetime.now().strftime('%H:%M:%S')}")
