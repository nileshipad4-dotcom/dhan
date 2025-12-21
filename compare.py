import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# -------------------------------------------------
# PAGE CONFIG
# -------------------------------------------------
st.set_page_config(layout="wide")
st.title("📊 NIFTY / BANKNIFTY – Max Pain + Greeks Comparison")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60_000, key="refresh")
except Exception:
    pass

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def ist_hhmm():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M")

def rotated_time_sort(times, pivot="09:15"):
    pivot_min = int(pivot[:2]) * 60 + int(pivot[3:])
    def key(t):
        h, m = map(int, t.split(":"))
        return ((h * 60 + m) - pivot_min) % (24 * 60)
    return sorted(times, key=key, reverse=True)

FACTOR = 10_000

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I", "security_id": 256265},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I", "security_id": 260105},
}

HEADERS = {
    "client-id": "1102712380",
    "access-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY2NDQwMzk5LCJpYXQiOjE3NjYzNTM5OTksInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.pLY-IzrzCrJIYWLLxo5_FD10k4F1MkgFQB9BOyQm5kIf969v7q0nyxvfyl2NniyhrWDiVWWACAWrW8kxIf3cxA",
    "Content-Type": "application/json",
}

UNDERLYING = st.sidebar.selectbox("Index", list(UNDERLYINGS.keys()))
CSV_PATH = f"data/{UNDERLYING.lower()}.csv"

# -------------------------------------------------
# LIVE INDEX PRICE
# -------------------------------------------------
@st.cache_data(ttl=10)
def get_index_price(sec_id):
    r = requests.post(
        f"{API_BASE}/marketfeed/ltp",
        headers=HEADERS,
        json={"NSE_IDX": [sec_id]},
        timeout=10,
    )
    if r.status_code != 200:
        return None
    return r.json()["data"].get(str(sec_id), {}).get("ltp")

spot = get_index_price(UNDERLYINGS[UNDERLYING]["security_id"])
st.sidebar.metric("Live Price", f"{spot:.2f}" if spot else "N/A")

# -------------------------------------------------
# LOAD HISTORICAL CSV
# -------------------------------------------------
df = pd.read_csv(CSV_PATH)

df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
df["timestamp"] = df["timestamp"].astype(str).str[-5:]

# -------------------------------------------------
# TIME SELECTION
# -------------------------------------------------
timestamps = rotated_time_sort(df["timestamp"].dropna().unique())
t1 = st.selectbox("Time-1 (Latest)", timestamps, 0)
t2 = st.selectbox("Time-2 (Previous)", timestamps, 1)

# -------------------------------------------------
# HISTORICAL MAX PAIN
# -------------------------------------------------
mp_t1 = df[df["timestamp"] == t1].groupby("Strike")["Max Pain"].sum().rename(f"MP ({t1})")
mp_t2 = df[df["timestamp"] == t2].groupby("Strike")["Max Pain"].sum().rename(f"MP ({t2})")

merged = pd.concat([mp_t1, mp_t2], axis=1).reset_index()
merged["Δ MP (T1 − T2)"] = merged[f"MP ({t1})"] - merged[f"MP ({t2})"]

# -------------------------------------------------
# T1 GREEKS / IV SNAPSHOT (BY STRIKE)
# -------------------------------------------------
t1_base = (
    df[df["timestamp"] == t1]
    .groupby("Strike", as_index=False)
    .agg(
        CE_IV_T1=("CE IV", "mean"),
        CE_Delta_T1=("CE Delta", "mean"),
        CE_Gamma_T1=("CE Gamma", "mean"),
        CE_Vega_T1=("CE Vega", "mean"),
        PE_IV_T1=("PE IV", "mean"),
        PE_Delta_T1=("PE Delta", "mean"),
        PE_Gamma_T1=("PE Gamma", "mean"),
        PE_Vega_T1=("PE Vega", "mean"),
    )
)

merged = merged.merge(t1_base, on="Strike", how="left")

# -------------------------------------------------
# LIVE OPTION CHAIN
# -------------------------------------------------
@st.cache_data(ttl=30)
def fetch_live_chain():
    cfg = UNDERLYINGS[UNDERLYING]

    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"]},
    )
    expiries = r.json().get("data", [])
    if not expiries:
        return None

    expiry = expiries[0]

    r = requests.post(
        f"{API_BASE}/optionchain",
        headers=HEADERS,
        json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"], "Expiry": expiry},
    )
    return r.json().get("data", {}).get("oc")

oc = fetch_live_chain()

# -------------------------------------------------
# LIVE MAX PAIN + GREEKS
# -------------------------------------------------
if oc:
    rows = []
    for strike, v in oc.items():
        ce, pe = v.get("ce", {}), v.get("pe", {})
        rows.append({
            "Strike": float(strike),

            "CE LTP": ce.get("last_price", 0),
            "CE OI": ce.get("oi", 0),
            "PE LTP": pe.get("last_price", 0),
            "PE OI": pe.get("oi", 0),

            "CE IV L": ce.get("implied_volatility"),
            "CE Delta L": ce.get("greeks", {}).get("delta"),
            "CE Gamma L": ce.get("greeks", {}).get("gamma"),
            "CE Vega L": ce.get("greeks", {}).get("vega"),

            "PE IV L": pe.get("implied_volatility"),
            "PE Delta L": pe.get("greeks", {}).get("delta"),
            "PE Gamma L": pe.get("greeks", {}).get("gamma"),
            "PE Vega L": pe.get("greeks", {}).get("vega"),
        })

    live = pd.DataFrame(rows).sort_values("Strike")

    # ---- LIVE MAX PAIN ----
    A, B = live["CE LTP"], live["CE OI"]
    G, L, M = live["Strike"], live["PE OI"], live["PE LTP"]

    live["MP_live"] = [
        round(
            (
                -sum(A[i:] * B[i:])
                + G.iloc[i] * sum(B[:i])
                - sum(G[:i] * B[:i])
                - sum(M[:i] * L[:i])
                + sum(G[i:] * L[i:])
                - G.iloc[i] * sum(L[i:])
            ) / 10000
        )
        for i in range(len(live))
    ]

    now = ist_hhmm()

    merged = merged.merge(
        live[["Strike", "MP_live"]].rename(columns={"MP_live": f"MP ({now})"}),
        on="Strike",
        how="left",
    )

    merged[f"Δ MP (Live − {t1})"] = merged[f"MP ({now})"] - merged[f"MP ({t1})"]

    # ---- MERGE LIVE GREEKS ----
    merged = merged.merge(
        live[[
            "Strike",
            "CE IV L","CE Delta L","CE Gamma L","CE Vega L",
            "PE IV L","PE Delta L","PE Gamma L","PE Vega L",
        ]],
        on="Strike",
        how="left",
    )

    # ---- GREEKS / IV DELTAS (CORRECT) ----
    merged["CE IV Δ"]     = (merged["CE IV L"]     - merged["CE_IV_T1"])     * FACTOR
    merged["CE Delta Δ"]  = (merged["CE Delta L"]  - merged["CE_Delta_T1"])  * FACTOR
    merged["CE Gamma Δ"]  = (merged["CE Gamma L"]  - merged["CE_Gamma_T1"])  * FACTOR
    merged["CE Vega Δ"]   = (merged["CE Vega L"]   - merged["CE_Vega_T1"])   * FACTOR

    merged["PE IV Δ"]     = (merged["PE IV L"]     - merged["PE_IV_T1"])     * FACTOR
    merged["PE Delta Δ"]  = (merged["PE Delta L"]  - merged["PE_Delta_T1"])  * FACTOR
    merged["PE Gamma Δ"]  = (merged["PE Gamma L"]  - merged["PE_Gamma_T1"])  * FACTOR
    merged["PE Vega Δ"]   = (merged["PE Vega L"]   - merged["PE_Vega_T1"])   * FACTOR

# -------------------------------------------------
# FINAL DISPLAY
# -------------------------------------------------
final = merged.sort_values("Strike").round(0)

st.dataframe(
    final,
    use_container_width=True,
    height=750,
)

st.caption(
    "MP = Max Pain | Δ = Live − Time-1 | Greeks & IV scaled ×10000 | Live price shown in sidebar"
)
