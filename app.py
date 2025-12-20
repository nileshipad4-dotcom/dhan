
import streamlit as st
import requests
import pandas as pd

# ================== CONFIG ==================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJwX2lwIjoiIiwic19pcCI6IiIsImlzcyI6ImRoYW4iLCJwYXJ0bmVySWQiOiIiLCJleHAiOjE3NjYzNDc3ODYsImlhdCI6MTc2NjI2MTM4NiwidG9rZW5Db25zdW1lclR5cGUiOiJTRUxGIiwid2ViaG9va1VybCI6Imh0dHBzOi8vbG9jYWxob3N0IiwiZGhhbkNsaWVudElkIjoiMTEwMjcxMjM4MCJ9.uQ4LyVOZqiy1ZyIENwcBT0Eei8taXbR8KgNW40NV0Y3nR_AQsmAC3JtZSoFE5p2xBwwB3q6ko_JEGTe7x_2ZTA"

API_BASE = "https://api.dhan.co/v2"
UNDERLYING_SCRIP = 13      # NIFTY 50 underlying
UNDERLYING_SEG = "IDX_I"   # segment for index
# ===========================================

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

@st.cache_data
def fetch_expiries():
    """
    Fetches list of expiry dates for the NIFTY option chain.
    """
    url = f"{API_BASE}/optionchain/expirylist"
    payload = {
        "UnderlyingScrip": UNDERLYING_SCRIP,
        "UnderlyingSeg": UNDERLYING_SEG
    }
    r = requests.post(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json().get("data", [])

def fetch_option_chain(expiry):
    """
    Fetches the raw option chain for a selected expiry
    """
    url = f"{API_BASE}/optionchain"
    payload = {
        "UnderlyingScrip": UNDERLYING_SCRIP,
        "UnderlyingSeg": UNDERLYING_SEG,
        "Expiry": expiry
    }
    r = requests.post(url, headers=HEADERS, json=payload)
    r.raise_for_status()
    return r.json().get("data", {}).get("oc", {})

# =============== STREAMLIT UI ===============
st.set_page_config(page_title="NIFTY Option Chain (DhanHQ)", layout="wide")
st.title("📊 NIFTY Option Chain – DhanHQ API")

try:
    expiry_list = fetch_expiries()
except Exception as e:
    st.error("Failed to fetch expiry list. Check your client-id / token or network.")
    st.stop()

if not expiry_list:
    st.warning("No expiry dates returned by the API.")
    st.stop()

selected_expiry = st.selectbox("Select Expiry", expiry_list)

if st.button("Load Chain"):
    with st.spinner("Fetching option chain…"):
        raw_chain = fetch_option_chain(selected_expiry)

    rows = []
    for strike, strike_data in raw_chain.items():
        ce = strike_data.get("ce", {})
        pe = strike_data.get("pe", {})

        rows.append({
            "Strike": float(strike),

            "CE LTP": ce.get("last_price"),
            "CE OI": ce.get("oi"),
            "CE IV": ce.get("implied_volatility"),
            "CE Delta": ce.get("greeks", {}).get("delta"),
            "CE Theta": ce.get("greeks", {}).get("theta"),
            "CE Gamma": ce.get("greeks", {}).get("gamma"),
            "CE Vega": ce.get("greeks", {}).get("vega"),

            "PE LTP": pe.get("last_price"),
            "PE OI": pe.get("oi"),
            "PE IV": pe.get("implied_volatility"),
            "PE Delta": pe.get("greeks", {}).get("delta"),
            "PE Theta": pe.get("greeks", {}).get("theta"),
            "PE Gamma": pe.get("greeks", {}).get("gamma"),
            "PE Vega": pe.get("greeks", {}).get("vega"),
        })

    df = pd.DataFrame(rows).sort_values("Strike")

    st.subheader(f"🔁 Option Chain for {selected_expiry}")
    st.dataframe(df, use_container_width=True)
