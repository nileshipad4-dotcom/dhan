

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
    "NIFTY": {"scrip": 13, "seg": "IDX_I", "security_id": 256265},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I", "security_id": 260105}
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
    r = requests.post(
        f"{API_BASE}/marketfeed/ltp",
        headers=HEADERS,
        json={"NSE_IDX": [security_id]}
    )
    if r.status_code != 200:
        return None, None

    data = r.json()["data"].get(str(security_id), {})
    return data.get("ltp"), data.get("previous_close")


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
        json={"UnderlyingScrip": scrip, "UnderlyingSeg": seg, "Expiry": expiry}
    )
    return r.json().get("data") if r.status_code == 200 else None


# =============== MAX PAIN ==================
def compute_max_pain(df):
    A = df["CE LTP"].fillna(0).values
    B = df["CE OI"].fillna(0).values
    G = df["Strike"].fillna(0).values
    L = df["PE OI"].fillna(0).values
    M = df["PE LTP"].fillna(0).values

    U = []
    for i in range(len(df)):
        Q = -sum(A[i:] * B[i:])
        R = G[i] * sum(B[:i]) - sum(G[:i] * B[:i])
        S = -sum(M[:i] * L[:i])
        T = sum(G[i:] * L[i:]) - G[i] * sum(L[i:])
        U.append(int((Q + R + S + T) / 10000))

    df["Max Pain"] = U
    return df


# =============== UI =========================
st.title("📊 Option Chain – DhanHQ")

symbol = st.selectbox("Select Index", UNDERLYINGS.keys())
cfg = UNDERLYINGS[symbol]

# -------- LIVE INDEX PRICE ------------------
index_ltp, prev_close = get_index_price(cfg["security_id"])
pct_change = ((index_ltp - prev_close) / prev_close * 100) if index_ltp and prev_close else None

c1, c2, c3 = st.columns(3)
c1.metric("Current Price", f"{index_ltp:.2f}" if index_ltp else "N/A")
c2.metric("Previous Close", f"{prev_close:.2f}" if prev_close else "N/A")
c3.metric("% Change", f"{pct_change:.2f}%" if pct_change else "N/A")

# -------- OPTION CHAIN ---------------------
expiries = get_expiries(cfg["scrip"], cfg["seg"])
if not expiries:
    st.stop()

expiry = expiries[0]
data = get_option_chain(cfg["scrip"], cfg["seg"], expiry)
if not data:
    st.stop()

oc = data["oc"]
strikes = sorted(float(k) for k in oc.keys())

# -------- CENTER STRIKE --------------------
if index_ltp is not None:
    center = min(strikes, key=lambda x: abs(x - index_ltp))
else:
    center = strikes[len(strikes) // 2]

idx = strikes.index(center)
selected_strikes = strikes[max(0, idx - 20): idx + 21]

# -------- BUILD TABLE ----------------------
rows = []
for strike in selected_strikes:
    s = oc.get(f"{strike:.6f}", {})
    ce, pe = s.get("ce", {}), s.get("pe", {})

    rows.append({
        "Strike": int(round(strike)),

        # ----- CE -----
        "CE LTP": round(ce["last_price"], 2) if ce.get("last_price") else None,
        "CE OI": ce.get("oi"),
        "CE Volume": ce.get("volume"),
        "CE IV": int(ce["implied_volatility"] * 10000)
        if ce.get("implied_volatility") is not None else None,
        "CE Delta": int(ce["greeks"]["delta"] * 100000)
        if ce.get("greeks", {}).get("delta") is not None else None,
        "CE Gamma": int(ce["greeks"]["gamma"] * 10000000)
        if ce.get("greeks", {}).get("gamma") is not None else None,
        "CE Vega": int(ce["greeks"]["vega"] * 10000)
        if ce.get("greeks", {}).get("vega") is not None else None,

        # ----- PE -----
        "PE LTP": round(pe["last_price"], 2) if pe.get("last_price") else None,
        "PE OI": pe.get("oi"),
        "PE Volume": pe.get("volume"),
        "PE IV": int(pe["implied_volatility"] * 10000)
        if pe.get("implied_volatility") is not None else None,
        "PE Delta": int(pe["greeks"]["delta"] * 100000)
        if pe.get("greeks", {}).get("delta") is not None else None,
        "PE Gamma": int(pe["greeks"]["gamma"] * 10000000)
        if pe.get("greeks", {}).get("gamma") is not None else None,
        "PE Vega": int(pe["greeks"]["vega"] * 10000)
        if pe.get("greeks", {}).get("vega") is not None else None,
    })

df = pd.DataFrame(rows)

# -------- MAX PAIN -------------------------
df = compute_max_pain(df)
df["timestamp"] = datetime.now()
true_max_pain_strike = df.loc[df["Max Pain"].idxmin(), "Strike"]

# -------- ATM STRIKES ----------------------
if index_ltp is not None:
    lower = max(df["Strike"][df["Strike"] <= index_ltp], default=None)
    upper = min(df["Strike"][df["Strike"] >= index_ltp], default=None)
else:
    lower = upper = None

def highlight_rows(row):
    if row["Strike"] == true_max_pain_strike:
        return ["background-color:#8B0000;color:white"] * len(row)
    if row["Strike"] in [lower, upper]:
        return ["background-color:#003366;color:white"] * len(row)
    return [""] * len(row)

st.dataframe(df.style.apply(highlight_rows, axis=1), use_container_width=True)

st.caption(f"⏱ Auto-refresh every 30 seconds | {datetime.now().strftime('%H:%M:%S')}")
