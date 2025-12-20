
import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from datetime import datetime

# ================= CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJwX2lwIjoiIiwic19pcCI6IiIsImlzcyI6ImRoYW4iLCJwYXJ0bmVySWQiOiIiLCJleHAiOjE3NjYzNDc3ODYsImlhdCI6MTc2NjI2MTM4NiwidG9rZW5Db25zdW1lclR5cGUiOiJTRUxGIiwid2ViaG9va1VybCI6Imh0dHBzOi8vbG9jYWxob3N0IiwiZGhhbkNsaWVudElkIjoiMTEwMjcxMjM4MCJ9.uQ4LyVOZqiy1ZyIENwcBT0Eei8taXbR8KgNW40NV0Y3nR_AQsmAC3JtZSoFE5p2xBwwB3q6ko_JEGTe7x_2ZTA"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {
        "scrip": 13,
        "seg": "IDX_I",
        "security_id": 256265
    },
    "BANKNIFTY": {
        "scrip": 25,
        "seg": "IDX_I",
        "security_id": 260105
    }
}

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# =============== PAGE CONFIG ===============
st.set_page_config(layout="wide")
st_autorefresh(interval=30_000, key="refresh")

# =============== API FUNCTIONS ===============
@st.cache_data(ttl=5)
def get_index_price(security_id):
    """
    CORRECT way to fetch index LTP using Market Quote API
    """
    url = f"{API_BASE}/marketfeed/ltp"
    payload = {
        "NSE_IDX": [security_id]   # 🔥 THIS WAS THE BUG
    }

    r = requests.post(url, headers=HEADERS, json=payload)

    if r.status_code != 200:
        return None, None

    data = r.json().get("data", {})
    idx_data = data.get(str(security_id), {})

    ltp = idx_data.get("ltp")
    prev_close = idx_data.get("previous_close")

    return ltp, prev_close


@st.cache_data(ttl=120)
def get_expiries(scrip, seg):
    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": scrip, "UnderlyingSeg": seg}
    )
    return r.json().get("data", []) if r.status_code == 200 else []


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
    return r.json().get("data") if r.status_code == 200 else None

# =============== UI =========================
st.title("📊 Option Chain – DhanHQ")

symbol = st.selectbox("Select Index", list(UNDERLYINGS.keys()))
cfg = UNDERLYINGS[symbol]

# -------- LIVE PRICE (NOW WORKS) ----------
index_ltp, prev_close = get_index_price(cfg["security_id"])

pct_change = (
    ((index_ltp - prev_close) / prev_close) * 100
    if index_ltp and prev_close else None
)

c1, c2, c3 = st.columns(3)
c1.metric("Current Price", f"{index_ltp:.2f}" if index_ltp else "N/A")
c2.metric("Previous Close", f"{prev_close:.2f}" if prev_close else "N/A")
c3.metric("% Change", f"{pct_change:.2f}%" if pct_change else "N/A")

# -------- OPTION CHAIN ---------------------
expiries = get_expiries(cfg["scrip"], cfg["seg"])
if not expiries:
    st.warning("No expiry data")
    st.stop()

expiry = expiries[0]

data = get_option_chain(cfg["scrip"], cfg["seg"], expiry)
if not data:
    st.warning("Option chain unavailable")
    st.stop()

oc = data.get("oc", {})
strikes = sorted(float(k) for k in oc.keys())

# Center around LIVE PRICE
center = (
    min(strikes, key=lambda x: abs(x - index_ltp))
    if index_ltp else
    strikes[len(strikes) // 2]
)

idx = strikes.index(center)
selected_strikes = strikes[max(0, idx - 20): idx + 21]

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
        "PE LTP": pe.get("last_price"),
        "PE OI": pe.get("oi"),
        "PE IV": pe.get("implied_volatility"),
        "PE Delta": pe.get("greeks", {}).get("delta"),
    })

df = pd.DataFrame(rows)

# -------- HIGHLIGHT TWO STRIKES ------------
highlight = []
if index_ltp:
    lower = max([s for s in df["Strike"] if s <= index_ltp], default=None)
    upper = min([s for s in df["Strike"] if s >= index_ltp], default=None)
    highlight = [lower, upper]

def highlight_rows(row):
    if row["Strike"] in highlight:
        return ["background-color:#003366;color:white"] * len(row)
    return [""] * len(row)

st.dataframe(df.style.apply(highlight_rows, axis=1), use_container_width=True)

st.caption(f"⏱ Auto-refresh 30s | {datetime.now().strftime('%H:%M:%S')}")
