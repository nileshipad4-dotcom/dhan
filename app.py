
import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from datetime import datetime

# ================== CONFIG ==================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJwX2lwIjoiIiwic19pcCI6IiIsImlzcyI6ImRoYW4iLCJwYXJ0bmVySWQiOiIiLCJleHAiOjE3NjYzNDc3ODYsImlhdCI6MTc2NjI2MTM4NiwidG9rZW5Db25zdW1lclR5cGUiOiJTRUxGIiwid2ViaG9va1VybCI6Imh0dHBzOi8vbG9jYWxob3N0IiwiZGhhbkNsaWVudElkIjoiMTEwMjcxMjM4MCJ9.uQ4LyVOZqiy1ZyIENwcBT0Eei8taXbR8KgNW40NV0Y3nR_AQsmAC3JtZSoFE5p2xBwwB3q6ko_JEGTe7x_2ZTA"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I"},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I"}
}
# ===========================================

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# =============== PAGE CONFIG ===============
st.set_page_config(layout="wide")

# -------- AUTO REFRESH (30 sec) ------------
st_autorefresh(interval=30_000, key="refresh")

# =============== API FUNCTIONS ===============
@st.cache_data(ttl=120)
def get_expiries(scrip, seg):
    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": scrip, "UnderlyingSeg": seg}
    )
    if r.status_code != 200:
        return []
    return r.json().get("data", [])


@st.cache_data(ttl=30)
def get_option_chain(scrip, seg, expiry):
    r = requests.post(
        f"{API_BASE}/optionchain",
        headers=HEADERS,
        json={
            "UnderlyingScrip": scrip,
            "UnderlyingSeg": seg,
            "Expiry": expiry
        }
    )
    if r.status_code != 200:
        return None
    return r.json().get("data")

# =============== UI =========================
st.title("📊 Option Chain – DhanHQ")

# -------- DROPDOWN TO TOGGLE UNDERLYING -----
selected_symbol = st.selectbox(
    "Select Index",
    options=list(UNDERLYINGS.keys())
)

cfg = UNDERLYINGS[selected_symbol]

# -------- FETCH EXPIRY ----------------------
expiries = get_expiries(cfg["scrip"], cfg["seg"])
if not expiries:
    st.warning("No expiry data available")
    st.stop()

expiry = expiries[0]  # nearest expiry

data = get_option_chain(cfg["scrip"], cfg["seg"], expiry)
if not data:
    st.warning("Option chain unavailable")
    st.stop()

oc = data.get("oc", {})
if not oc:
    st.warning("No option chain data")
    st.stop()

# ---- LIVE INDEX PRICE (for highlighting) ---
spot_price = data.get("spot_price")

strikes = sorted(float(k) for k in oc.keys())

# Center strikes safely
if spot_price:
    center_strike = min(strikes, key=lambda x: abs(x - spot_price))
else:
    center_strike = strikes[len(strikes) // 2]

idx = strikes.index(center_strike)
selected_strikes = strikes[max(0, idx - 20): idx + 21]

# -------- BUILD TABLE -----------------------
rows = []
for strike in selected_strikes:
    s = oc.get(f"{strike:.6f}", {})
    ce = s.get("ce", {})
    pe = s.get("pe", {})

    rows.append({
        "Strike": strike,

        "CE LTP": ce.get("last_price"),
        "CE OI": ce.get("oi"),
        "CE IV": ce.get("implied_volatility"),
        "CE Delta": ce.get("greeks", {}).get("delta"),
        "CE Gamma": ce.get("greeks", {}).get("gamma"),
        "CE Vega": ce.get("greeks", {}).get("vega"),

        "PE LTP": pe.get("last_price"),
        "PE OI": pe.get("oi"),
        "PE IV": pe.get("implied_volatility"),
        "PE Delta": pe.get("greeks", {}).get("delta"),
        "PE Gamma": pe.get("greeks", {}).get("gamma"),
        "PE Vega": pe.get("greeks", {}).get("vega"),
    })

df = pd.DataFrame(rows)

# -------- HIGHLIGHT TWO STRIKES AROUND SPOT --
highlight_strikes = []
if spot_price:
    lower = max([s for s in df["Strike"] if s <= spot_price], default=None)
    upper = min([s for s in df["Strike"] if s >= spot_price], default=None)
    highlight_strikes = [lower, upper]

def highlight_rows(row):
    if row["Strike"] in highlight_strikes:
        return ["background-color: #0b3c5d; color: white"] * len(row)
    return [""] * len(row)

styled_df = df.style.apply(highlight_rows, axis=1)

st.subheader(f"{selected_symbol} Option Chain (Nearest Expiry)")
st.dataframe(styled_df, use_container_width=True)

st.caption(
    f"⏱ Auto-refresh every 30 seconds | Last updated: {datetime.now().strftime('%H:%M:%S')}"
)
