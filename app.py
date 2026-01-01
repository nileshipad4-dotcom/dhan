# ================= CONFIG =================

import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta
import os

# ================= API CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY3MzE1ODk2LCJpYXQiOjE3NjcyMjk0OTYsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.WpIf1CiWyqLGZB4DmTAwnRj8_sziPmkYzfxKJ-80oO9C85jeQ3JHR7YM1R4q-LySMuzViWUU32mhxK6HgjajXQ"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {
        "security_id": 256265,
        "scrip": 13,
        "seg": "IDX_I",
        "center": 26000
    },
    "BANKNIFTY": {
        "security_id": 260105,
        "scrip": 25,
        "seg": "IDX_I",
        "center": 60000
    },
    "MIDCAP NIFTY SELECT": {
        "security_id": 260113,
        "scrip": 28,
        "seg": "IDX_I",
        "center": 13600
    },
    "SENSEX": {
        "security_id": 256777,
        "scrip": 51,
        "seg": "IDX_I",
        "center": 84000
    },
}

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# ================= PAGE =================
st.set_page_config(layout="wide")
st_autorefresh(interval=30_000, key="refresh")
st.title("📊 Option Chain – Max Pain (Collector Logic)")

# ================= DROPDOWNS =================
symbol = st.selectbox("Select Index", list(UNDERLYINGS.keys()))
cfg = UNDERLYINGS[symbol]

# ================= EXPIRIES =================
def get_expiries(scrip, seg):
    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": scrip, "UnderlyingSeg": seg}
    )
    return r.json().get("data", []) if r.status_code == 200 else []

expiries = get_expiries(cfg["scrip"], cfg["seg"])
if not expiries:
    st.error("No expiries returned by API")
    st.stop()

expiry = st.selectbox("Select Expiry (next 10)", expiries[:10])

# ================= OPTION CHAIN =================
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

data = get_option_chain(cfg["scrip"], cfg["seg"], expiry)
if not data or "oc" not in data:
    st.error("Option chain data not available")
    st.stop()

oc = data["oc"]
strikes = sorted(float(s) for s in oc.keys())

# ================= STRIKE SELECTION (EXACT MATCH) =================
center = cfg["center"]

below = [s for s in strikes if s <= center][-35:]
above = [s for s in strikes if s > center][:36]
selected = sorted(set(below + above))

# ================= BUILD TABLE =================
rows = []
for s in selected:
    v = oc.get(f"{s:.6f}", {})
    ce, pe = v.get("ce", {}), v.get("pe", {})

    rows.append({
        "Strike": int(s),

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

df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

# ================= FORCE NUMERIC (IDENTICAL) =================
num_cols = [
    "CE LTP","CE OI","CE IV","CE Delta","CE Gamma","CE Vega",
    "PE LTP","PE OI","PE IV","PE Delta","PE Gamma","PE Vega"
]
for c in num_cols:
    df[c] = pd.to_numeric(df[c], errors="coerce")

# ================= MAX PAIN (IDENTICAL FORMULA) =================
def compute_max_pain(df):
    A = df["CE LTP"].fillna(0)
    B = df["CE OI"].fillna(0)
    G = df["Strike"]
    L = df["PE OI"].fillna(0)
    M = df["PE LTP"].fillna(0)

    mp = []
    for i in range(len(df)):
        mp.append(int((
            -sum(A[i:] * B[i:])
            + G[i] * sum(B[:i]) - sum(G[:i] * B[:i])
            - sum(M[:i] * L[:i])
            + sum(G[i:] * L[i:]) - G[i] * sum(L[i:])
        ) / 10000))

    df["Max Pain"] = mp
    return df

df = compute_max_pain(df)

# ================= DISPLAY =================
true_mp_strike = df.loc[df["Max Pain"].idxmin(), "Strike"]

def highlight_rows(row):
    if row["Strike"] == true_mp_strike:
        return ["background-color:#8B0000;color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    df.style.apply(highlight_rows, axis=1),
    use_container_width=True
)

st.caption(
    f"⏱ Auto-refresh every 30 seconds | "
    f"{(datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%H:%M:%S')}"
)
