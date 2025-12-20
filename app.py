import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# ================== CONFIG ==================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJwX2lwIjoiIiwic19pcCI6IiIsImlzcyI6ImRoYW4iLCJwYXJ0bmVySWQiOiIiLCJleHAiOjE3NjYzNDc3ODYsImlhdCI6MTc2NjI2MTM4NiwidG9rZW5Db25zdW1lclR5cGUiOiJTRUxGIiwid2ViaG9va1VybCI6Imh0dHBzOi8vbG9jYWxob3N0IiwiZGhhbkNsaWVudElkIjoiMTEwMjcxMjM4MCJ9.uQ4LyVOZqiy1ZyIENwcBT0Eei8taXbR8KgNW40NV0Y3nR_AQsmAC3JtZSoFE5p2xBwwB3q6ko_JEGTe7x_2ZTA"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {
        "scrip": 13,
        "seg": "IDX_I"
    },
    "BANKNIFTY": {
        "scrip": 25,
        "seg": "IDX_I"
    }
}
# ===========================================

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# ---------- AUTO REFRESH ----------
st.set_page_config(layout="wide")
st.autorefresh(interval=30_000, key="refresh")

# ---------- API FUNCTIONS ----------
@st.cache_data(ttl=60)
def get_expiries(scrip, seg):
    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": scrip, "UnderlyingSeg": seg}
    )
    r.raise_for_status()
    return r.json()["data"]

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
    r.raise_for_status()
    return r.json()["data"]

# ---------- UI ----------
st.title("📊 NIFTY & BANKNIFTY Option Chain – DhanHQ")

for name, cfg in UNDERLYINGS.items():
    st.markdown(f"## 🔹 {name}")

    expiries = get_expiries(cfg["scrip"], cfg["seg"])
    expiry = expiries[0]

    data = get_option_chain(cfg["scrip"], cfg["seg"], expiry)

    spot = data.get("spot_price")
    prev_close = data.get("previous_close_price")
    pct_change = ((spot - prev_close) / prev_close) * 100 if prev_close else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Spot Price", f"{spot:.2f}")
    col2.metric("Prev Close", f"{prev_close:.2f}")
    col3.metric("% Change", f"{pct_change:.2f}%")

    oc = data["oc"]

    # -------- FILTER ±20 STRIKES AROUND PREV CLOSE --------
    strikes = sorted(float(k) for k in oc.keys())
    nearest = min(strikes, key=lambda x: abs(x - prev_close))
    idx = strikes.index(nearest)

    lower = max(0, idx - 20)
    upper = min(len(strikes), idx + 21)
    selected_strikes = strikes[lower:upper]

    rows = []
    for strike in selected_strikes:
        s = oc[str(f"{strike:.6f}")]
        ce, pe = s.get("ce", {}), s.get("pe", {})

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
    st.dataframe(df, use_container_width=True)

st.caption(f"⏱ Auto-refresh every 30 seconds | Last updated: {datetime.now().strftime('%H:%M:%S')}")
