import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# ================= CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJwX2lwIjoiIiwic19pcCI6IiIsImlzcyI6ImRoYW4iLCJwYXJ0bmVySWQiOiIiLCJleHAiOjE3NjYzNDc3ODYsImlhdCI6MTc2NjI2MTM4NiwidG9rZW5Db25zdW1lclR5cGUiOiJTRUxGIiwid2ViaG9va1VybCI6Imh0dHBzOi8vbG9jYWxob3N0IiwiZGhhbkNsaWVudElkIjoiMTEwMjcxMjM4MCJ9.uQ4LyVOZqiy1ZyIENwcBT0Eei8taXbR8KgNW40NV0Y3nR_AQsmAC3JtZSoFE5p2xBwwB3q6ko_JEGTe7x_2ZTA"

API_BASE = "https://api.dhan.co/v2"
INSTRUMENT_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

st.set_page_config(layout="wide")
st.title("📊 All F&O Stocks – Option Chain (Single Table)")

# ============ LOAD F&O STOCKS =============
@st.cache_data(ttl=3600)
def get_fno_stocks():
    df = pd.read_csv(INSTRUMENT_URL, low_memory=False)

    # NSE F&O equities only
    fno = df[
        (df["SEM_SEGMENT"] == "NSE_FNO") &
        (df["SEM_INSTRUMENT_NAME"] == "OPTSTK")
    ]

    return (
        fno[["SEM_SMST_SECURITY_ID", "SEM_TRADING_SYMBOL"]]
        .drop_duplicates()
        .rename(columns={
            "SEM_SMST_SECURITY_ID": "security_id",
            "SEM_TRADING_SYMBOL": "symbol"
        })
    )

fno_stocks = get_fno_stocks()

st.info(f"Total F&O Stocks Loaded: {len(fno_stocks)}")

# ============ API HELPERS =================
def get_expiry(security_id):
    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": security_id, "UnderlyingSeg": "NSE_FNO"}
    )
    if r.status_code != 200:
        return None
    data = r.json().get("data", [])
    return data[0] if data else None


def get_option_chain(security_id, expiry):
    r = requests.post(
        f"{API_BASE}/optionchain",
        headers=HEADERS,
        json={
            "UnderlyingScrip": security_id,
            "UnderlyingSeg": "NSE_FNO",
            "Expiry": expiry
        }
    )
    if r.status_code != 200:
        return None
    return r.json().get("data", {}).get("oc", {})

# ============ BUILD TABLE =================
rows = []

MAX_STOCKS = st.slider("Max stocks to load (performance)", 1, 25, 5)

for _, stock in fno_stocks.head(MAX_STOCKS).iterrows():
    symbol = stock["symbol"]
    security_id = stock["security_id"]

    expiry = get_expiry(security_id)
    if not expiry:
        continue

    oc = get_option_chain(security_id, expiry)
    if not oc:
        continue

    strikes = sorted(float(k) for k in oc.keys())

    # Use middle strikes (no spot available reliably)
    mid = len(strikes) // 2
    selected = strikes[mid - 5: mid + 6]

    for strike in selected:
        s = oc.get(f"{strike:.6f}", {})
        ce = s.get("ce", {})
        pe = s.get("pe", {})

        rows.append({
            "Symbol": symbol,
            "Strike": strike,

            "CE LTP": ce.get("last_price"),
            "CE OI": ce.get("oi"),
            "CE Vol": ce.get("volume"),

            "CE IV": int(ce["implied_volatility"] * 10000)
            if ce.get("implied_volatility") is not None else None,

            "CE Δ": int(ce["greeks"]["delta"] * 100000)
            if ce.get("greeks", {}).get("delta") is not None else None,

            "CE Γ": int(ce["greeks"]["gamma"] * 10000000)
            if ce.get("greeks", {}).get("gamma") is not None else None,

            "CE V": int(ce["greeks"]["vega"] * 10000)
            if ce.get("greeks", {}).get("vega") is not None else None,

            "PE LTP": pe.get("last_price"),
            "PE OI": pe.get("oi"),
            "PE Vol": pe.get("volume"),

            "PE IV": int(pe["implied_volatility"] * 10000)
            if pe.get("implied_volatility") is not None else None,

            "PE Δ": int(pe["greeks"]["delta"] * 100000)
            if pe.get("greeks", {}).get("delta") is not None else None,

            "PE Γ": int(pe["greeks"]["gamma"] * 10000000)
            if pe.get("greeks", {}).get("gamma") is not None else None,

            "PE V": int(pe["greeks"]["vega"] * 10000)
            if pe.get("greeks", {}).get("vega") is not None else None,
        })

    # ---------- WHITE SEPARATOR ROW ----------
    rows.append({col: "" for col in rows[-1].keys()})

df = pd.DataFrame(rows)

st.dataframe(df, use_container_width=True)

st.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
