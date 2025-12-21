import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 NIFTY / BANKNIFTY – Max Pain + Greeks Comparison")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60_000, key="refresh")
except Exception:
    pass

# =================================================
# HELPERS
# =================================================
def ist_hhmm():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M")

def rotated_time_sort(times, pivot="09:15"):
    pivot_min = int(pivot[:2]) * 60 + int(pivot[3:])
    def key(t):
        h, m = map(int, t.split(":"))
        return ((h * 60 + m) - pivot_min) % (24 * 60)
    return sorted(times, key=key, reverse=True)

FACTOR = 10_000

# =================================================
# CONFIG
# =================================================
API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I", "security_id": 256265},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I", "security_id": 260105},
}

STRIKE_CENTER = {
    "NIFTY": 26000,
    "BANKNIFTY": 60000,
}

STRIKE_STEP = 100
STRIKES_BELOW = 25
STRIKES_ABOVE = 26

HEADERS = {
    "client-id": "1102712380",
    "access-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY2NDQwMzk5LCJpYXQiOjE3NjYzNTM5OTksInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.pLY-IzrzCrJIYWLLxo5_FD10k4F1MkgFQB9BOyQm5kIf969v7q0nyxvfyl2NniyhrWDiVWWACAWrW8kxIf3cxA",
    "Content-Type": "application/json",
}

UNDERLYING = st.sidebar.selectbox("Index", list(UNDERLYINGS.keys()))
CSV_PATH = f"data/{UNDERLYING.lower()}.csv"

CENTER = STRIKE_CENTER[UNDERLYING]
LOWER = CENTER - STRIKES_BELOW * STRIKE_STEP
UPPER = CENTER + STRIKES_ABOVE * STRIKE_STEP

# =================================================
# LIVE INDEX PRICE
# =================================================
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

# =================================================
# LOAD HISTORICAL CSV
# =================================================
df = pd.read_csv(CSV_PATH)

df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce").astype(int)
df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
df["timestamp"] = df["timestamp"].astype(str).str[-5:]

# ---- APPLY STRIKE WINDOW (HISTORICAL) ----
df = df[(df["Strike"] >= LOWER) & (df["Strike"] <= UPPER)]

# =================================================
# TIME SELECTION
# =================================================
timestamps = rotated_time_sort(df["timestamp"].dropna().unique())
t1 = st.selectbox("Time-1 (Latest)", timestamps, 0)
t2 = st.selectbox("Time-2 (Previous)", timestamps, 1)

# =================================================
# HISTORICAL MAX PAIN
# =================================================
mp_t1 = (
    df[df["timestamp"] == t1]
    .groupby("Strike", as_index=False)["Max Pain"]
    .mean()
    .rename(columns={"Max Pain": f"MP ({t1})"})
)

mp_t2 = (
    df[df["timestamp"] == t2]
    .groupby("Strike", as_index=False)["Max Pain"]
    .mean()
    .rename(columns={"Max Pain": f"MP ({t2})"})
)

# =================================================
# T1 GREEKS / IV BASE
# =================================================
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

# =================================================
# LIVE OPTION CHAIN
# =================================================
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
        json={
            "UnderlyingScrip": cfg["scrip"],
            "UnderlyingSeg": cfg["seg"],
            "Expiry": expiry,
        },
    )
    return r.json().get("data", {}).get("oc")

oc = fetch_live_chain()

# =================================================
# LIVE SNAPSHOT + LIVE MAX PAIN (WINDOWED)
# =================================================
live_df = None

if oc:
    rows = []
    for strike, v in oc.items():
        s = int(round(float(strike)))
        if not (LOWER <= s <= UPPER):
            continue

        ce, pe = v.get("ce", {}), v.get("pe", {})
        rows.append({
            "Strike": s,

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

    live_df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

    # ---- LIVE MAX PAIN ----
    A, B = live_df["CE LTP"], live_df["CE OI"]
    G, L, M = live_df["Strike"], live_df["PE OI"], live_df["PE LTP"]

    live_df["MP_live"] = [
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
        for i in range(len(live_df))
    ]

# =================================================
# FINAL STRICT MERGE
# =================================================
final = (
    mp_t1
    .merge(mp_t2, on="Strike", how="inner")
    .merge(t1_base, on="Strike", how="inner")
)

if live_df is not None:
    final = final.merge(
        live_df[[
            "Strike","MP_live",
            "CE IV L","CE Delta L","CE Gamma L","CE Vega L",
            "PE IV L","PE Delta L","PE Gamma L","PE Vega L",
        ]],
        on="Strike",
        how="inner",
    )

    now = ist_hhmm()

    final[f"MP ({now})"] = final["MP_live"]
    final[f"Δ MP (Live − {t1})"] = final[f"MP ({now})"] - final[f"MP ({t1})"]
    final[f"Δ MP (T1 − {t2})"] = final[f"MP ({t1})"] - final[f"MP ({t2})"]

    final["CE IV Δ"]    = (final["CE IV L"]    - final["CE_IV_T1"])    * FACTOR
    final["CE Delta Δ"] = (final["CE Delta L"] - final["CE_Delta_T1"]) * FACTOR
    final["CE Gamma Δ"] = (final["CE Gamma L"] - final["CE_Gamma_T1"]) * FACTOR
    final["CE Vega Δ"]  = (final["CE Vega L"]  - final["CE_Vega_T1"])  * FACTOR

    final["PE IV Δ"]    = (final["PE IV L"]    - final["PE_IV_T1"])    * FACTOR
    final["PE Delta Δ"] = (final["PE Delta L"] - final["PE_Delta_T1"]) * FACTOR
    final["PE Gamma Δ"] = (final["PE Gamma L"] - final["PE_Gamma_T1"]) * FACTOR
    final["PE Vega Δ"]  = (final["PE Vega L"]  - final["PE_Vega_T1"])  * FACTOR

# =================================================
# FINAL VIEW
# =================================================
final = final[[
    "Strike",
    f"MP ({now})",
    f"MP ({t1})",
    f"Δ MP (Live − {t1})",
    f"MP ({t2})",
    f"Δ MP (T1 − {t2})",
    "CE IV Δ","PE IV Δ",
    "CE Delta Δ","PE Delta Δ",
    "CE Gamma Δ","PE Gamma Δ",
    "CE Vega Δ","PE Vega Δ",
]].round(0)

st.dataframe(final, use_container_width=True, height=750)

st.caption(
    "Strike window: 25 below / 26 above | Δ = Live − T1 | Greeks ×10000 | Live price shown"
)
