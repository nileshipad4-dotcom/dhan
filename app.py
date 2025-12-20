import streamlit as st
import requests
import pandas as pd

# ================= CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJwX2lwIjoiIiwic19pcCI6IiIsImlzcyI6ImRoYW4iLCJwYXJ0bmVySWQiOiIiLCJleHAiOjE3NjYzNDc3ODYsImlhdCI6MTc2NjI2MTM4NiwidG9rZW5Db25zdW1lclR5cGUiOiJTRUxGIiwid2ViaG9va1VybCI6Imh0dHBzOi8vbG9jYWxob3N0IiwiZGhhbkNsaWVudElkIjoiMTEwMjcxMjM4MCJ9.uQ4LyVOZqiy1ZyIENwcBT0Eei8taXbR8KgNW40NV0Y3nR_AQsmAC3JtZSoFE5p2xBwwB3q6ko_JEGTe7x_2ZTA"

API_BASE = "https://api.dhan.co/v2"
UNDERLYING_SCRIP = 13      # NIFTY
UNDERLYING_SEG = "IDX_I"
# =========================================

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}


@st.cache_data
def get_expiry_list():
    url = f"{API_BASE}/optionchain/expirylist"
    payload = {
        "UnderlyingScrip": UNDERLYING_SCRIP,
        "UnderlyingSeg": UNDERLYING_SEG
    }
    r = requests.post(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json()["data"]


def get_option_chain(expiry):
    url = f"{API_BASE}/optionchain"
    payload = {
        "UnderlyingScrip": UNDERLYING_SCRIP,
        "UnderlyingSeg": UNDERLYING_SEG,
        "Expiry": expiry
    }
    r = requests.post(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json()["data"]["oc"]


# ================= STREAMLIT UI =================
st.set_page_config(page_title="NIFTY Option Chain", layout="wide")
st.title("📊 NIFTY Option Chain – Dhan API")

try:
    expiries = get_expiry_list()
except Exception as e:
    st.error("Authentication failed. Check client-id or access-token.")
    st.stop()

expiry = st.selectbox("Select Expiry", expiries)

if st.button("Load Option Chain"):
    with st.spinner("Fetching option chain..."):
        oc = get_option_chain(expiry)

    rows = []
    for strike, data in oc.items():
        ce = data.get("ce", {})
        pe = data.get("pe", {})

        rows.append({
            "Strike": float(strike),

            "CE LTP": ce.get("last_price"),
            "CE OI": ce.get("oi"),
            "CE Delta": ce.get("delta"),
            "CE Gamma": ce.get("gamma"),
            "CE Vega": ce.get("vega"),

            "PE LTP": pe.get("last_price"),
            "PE OI": pe.get("oi"),
            "PE Delta": pe.get("delta"),
            "PE Gamma": pe.get("gamma"),
            "PE Vega": pe.get("vega"),
        })

    df = pd.DataFrame(rows).sort_values("Strike")

    st.subheader(f"Option Chain – Expiry {expiry}")
    st.dataframe(df, use_container_width=True)
