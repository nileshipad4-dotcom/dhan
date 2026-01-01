# ================= CONFIG =================

import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import os

# ================= CSV STORAGE =================
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def save_to_csv(df, symbol, expiry):
    fname = f"{symbol.lower().replace(' ', '_')}_{expiry}.csv"
    file_path = f"{DATA_DIR}/{fname}"

    if os.path.exists(file_path):
        existing = pd.read_csv(file_path)
        last_time = pd.to_datetime(existing["timestamp"]).max()
        if (datetime.now() - last_time).total_seconds() < 300:
            return
        df.to_csv(file_path, mode="a", header=False, index=False)
    else:
        df.to_csv(file_path, index=False)


# ================= API CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY3MzE1ODk2LCJpYXQiOjE3NjcyMjk0OTYsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.WpIf1CiWyqLGZB4DmTAwnRj8_sziPmkYzfxKJ-80oO9C85jeQ3JHR7YM1R4q-LySMuzViWUU32mhxK6HgjajXQ"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I"},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I"},
    "FINNIFTY": {"scrip": 27, "seg": "IDX_I"},
    "MIDCAP NIFTY SELECT": {"scrip": 28, "seg": "IDX_I"},
    "SENSEX": {"scrip": 51, "seg": "IDX_I"},
}

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

# ================= PAGE =================
st.set_page_config(layout="wide")
st_autorefresh(interval=30_000, key="refresh")

st.title("📊 Option Chain – DhanHQ")

# ================= DROPDOWNS (ALWAYS VISIBLE) =================
symbol = st.selectbox("Select Index", list(UNDERLYINGS.keys()))
cfg = UNDERLYINGS[symbol]

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

expiries = get_expiries(cfg["scrip"], cfg["seg"])

if not expiries:
    st.warning("No expiries available")
    st.stop()

expiry = st.selectbox("Select Expiry", expiries[:10])

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

data = get_option_chain(cfg["scrip"], cfg["seg"], expiry)

if not data or "oc" not in data:
    st.warning("Option chain data not available")
    st.stop()

# ================= BUILD OPTION CHAIN =================
oc = data["oc"]
strikes = sorted(float(k) for k in oc.keys())

rows = []
for strike in strikes:
    s = oc.get(f"{strike:.6f}", {})
    ce, pe = s.get("ce", {}), s.get("pe", {})

    rows.append({
        "Strike": int(strike),

        "CE LTP": ce.get("last_price"),
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

        "PE LTP": pe.get("last_price"),
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

# ================= MAX PAIN =================
def compute_max_pain(df):
    A = df["CE LTP"].fillna(0).values
    B = df["CE OI"].fillna(0).values
    G = df["Strike"].values
    L = df["PE OI"].fillna(0).values
    M = df["PE LTP"].fillna(0).values

    mp = []
    for i in range(len(df)):
        Q = -sum(A[i:] * B[i:])
        R = G[i] * sum(B[:i]) - sum(G[:i] * B[:i])
        S = -sum(M[:i] * L[:i])
        T = sum(G[i:] * L[i:]) - G[i] * sum(L[i:])
        mp.append(int((Q + R + S + T) / 10000))

    df["Max Pain"] = mp
    return df

df = compute_max_pain(df)
df["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")

save_to_csv(df, symbol, expiry)

# ================= DISPLAY =================
true_mp = df.loc[df["Max Pain"].idxmin(), "Strike"]

def highlight(row):
    if row["Strike"] == true_mp:
        return ["background-color:#8B0000;color:white"] * len(row)
    return [""] * len(row)

st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True)

st.caption(f"⏱ Auto-refresh every 30 seconds | {datetime.now().strftime('%H:%M:%S')}")
