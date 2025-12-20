
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
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I"},
}
# ===========================================

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# =============== PAGE CONFIG ===============
st.set_page_config(page_title="Dhan Option Chain", layout="wide")
st_autorefresh(interval=30_000, key="refresh")

st.title("📊 NIFTY & BANKNIFTY Option Chain – DhanHQ")

# =============== API HELPERS ===============
def post_safe(url, payload):
    try:
        r = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text}"
        return r.json(), None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=60)
def get_expiries(scrip, seg):
    data, err = post_safe(
        f"{API_BASE}/optionchain/expirylist",
        {"UnderlyingScrip": scrip, "UnderlyingSeg": seg},
    )
    if err:
        return None, err
    return data.get("data"), None

def get_option_chain(scrip, seg, expiry):
    data, err = post_safe(
        f"{API_BASE}/optionchain",
        {
            "UnderlyingScrip": scrip,
            "UnderlyingSeg": seg,
            "Expiry": expiry,
        },
    )
    if err:
        return None, err
    return data.get("data"), None

# =============== UI LOOP ===============
for name, cfg in UNDERLYINGS.items():
    st.markdown(f"## 🔹 {name}")

    expiries, err = get_expiries(cfg["scrip"], cfg["seg"])
    if err:
        st.error(f"{name} expiry error: {err}")
        continue

    if not expiries:
        st.warning(f"No expiries returned for {name}")
        continue

    expiry = expiries[0]

    data, err = get_option_chain(cfg["scrip"], cfg["seg"], expiry)
    if err:
        st.error(f"{name} option chain error: {err}")
        continue

    spot = data.get("spot_price")
    prev_close = data.get("previous_close_price")

    if not spot or not prev_close:
        st.warning(f"{name}: Spot / Previous close unavailable")
        continue

    pct_change = ((spot - prev_close) / prev_close) * 100

    c1, c2, c3 = st.columns(3)
    c1.metric("Spot", f"{spot:.2f}")
    c2.metric("Prev Close", f"{prev_close:.2f}")
    c3.metric("% Change", f"{pct_change:.2f}%")

    oc = data.get("oc", {})
    if not oc:
        st.warning(f"{name}: Option chain empty")
        continue

    # ----- FILTER ±20 STRIKES AROUND PREV CLOSE -----
    strikes = sorted(float(k) for k in oc.keys())
    nearest = min(strikes, key=lambda x: abs(x - prev_close))
    idx = strikes.index(nearest)

    selected = strikes[max(0, idx - 20): idx + 21]

    rows = []
    for strike in selected:
        s = oc.get(f"{strike:.6f}", {})
        ce = s.get("ce", {})
        pe = s.get("pe", {})

        rows.append({
            "Strike": strike,
            "CE LTP": ce.get("last_price"),
            "CE OI": ce.get("oi"),
            "CE IV": ce.get("implied_volatility"),
            "CE Δ": ce.get("greeks", {}).get("delta"),
            "CE Γ": ce.get("greeks", {}).get("gamma"),
            "CE V": ce.get("greeks", {}).get("vega"),
            "PE LTP": pe.get("last_price"),
            "PE OI": pe.get("oi"),
            "PE IV": pe.get("implied_volatility"),
            "PE Δ": pe.get("greeks", {}).get("delta"),
            "PE Γ": pe.get("greeks", {}).get("gamma"),
            "PE V": pe.get("greeks", {}).get("vega"),
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True)

st.caption(
    f"⏱ Auto-refresh: 30 sec | Last update: {datetime.now().strftime('%H:%M:%S')}"
)
