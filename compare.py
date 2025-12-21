import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 NIFTY / BANKNIFTY – Max Pain + Greeks Δ")

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

def rotated_time_sort(times):
    return sorted(times, reverse=True)

FACTOR = 10000

# =================================================
# CONFIG
# =================================================
API_BASE = "https://api.dhan.co/v2"

HEADERS = {
    "client-id": "1102712380",
    "access-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY2NDQwMzk5LCJpYXQiOjE3NjYzNTM5OTksInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.pLY-IzrzCrJIYWLLxo5_FD10k4F1MkgFQB9BOyQm5kIf969v7q0nyxvfyl2NniyhrWDiVWWACAWrW8kxIf3cxA",
    "Content-Type": "application/json",
}

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I", "center": 26000},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I", "center": 60000},
}

UNDERLYING = st.sidebar.selectbox("Index", list(UNDERLYINGS.keys()))
CSV_PATH = f"data/{UNDERLYING.lower()}.csv"

# =================================================
# LOAD CSV (HISTORICAL)
# =================================================
df = pd.read_csv(CSV_PATH)

df["Strike"] = df["Strike"].astype(int)
df["timestamp"] = df["timestamp"].astype(str).str[-5:]

# =================================================
# IDENTICAL STRIKE SELECTION (MATCHES COLLECTOR)
# =================================================
center = UNDERLYINGS[UNDERLYING]["center"]
all_strikes = sorted(df["Strike"].unique())

below = [s for s in all_strikes if s <= center][-25:]
above = [s for s in all_strikes if s > center][:26]
SELECTED = set(below + above)

df = df[df["Strike"].isin(SELECTED)]

# =================================================
# TIME SELECTION
# =================================================
timestamps = rotated_time_sort(df["timestamp"].unique())
t1 = st.selectbox("Time-1 (Latest)", timestamps, 0)
t2 = st.selectbox("Time-2 (Previous)", timestamps, 1)

# =================================================
# HISTORICAL MAX PAIN
# =================================================
mp_t1 = df[df["timestamp"] == t1].groupby("Strike")["Max Pain"].mean()
mp_t2 = df[df["timestamp"] == t2].groupby("Strike")["Max Pain"].mean()

final = pd.DataFrame({
    f"MP ({t1})": mp_t1,
    f"MP ({t2})": mp_t2,
}).reset_index()

final[f"Δ MP (T1 − T2)"] = final[f"MP ({t1})"] - final[f"MP ({t2})"]

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

final = final.merge(t1_base, on="Strike", how="inner")

# =================================================
# LIVE OPTION CHAIN
# =================================================
@st.cache_data(ttl=30)
def fetch_live_oc():
    cfg = UNDERLYINGS[UNDERLYING]

    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"]},
    )
    expiries = r.json().get("data", [])
    if not expiries:
        return None

    r = requests.post(
        f"{API_BASE}/optionchain",
        headers=HEADERS,
        json={
            "UnderlyingScrip": cfg["scrip"],
            "UnderlyingSeg": cfg["seg"],
            "Expiry": expiries[0],
        },
    )
    return r.json().get("data", {}).get("oc")

# =================================================
# LIVE SNAPSHOT + LIVE MAX PAIN
# =================================================
def compute_live_snapshot(oc, strikes):
    rows = []

    for s in strikes:
        v = oc.get(f"{float(s):.6f}", {})
        ce, pe = v.get("ce", {}), v.get("pe", {})

        rows.append({
            "Strike": int(s),

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

    df_live = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

    A, B = df_live["CE LTP"], df_live["CE OI"]
    G, L, M = df_live["Strike"], df_live["PE OI"], df_live["PE LTP"]

    df_live["MP_live"] = [
        int((
            -sum(A[i:] * B[i:])
            + G[i] * sum(B[:i]) - sum(G[:i] * B[:i])
            - sum(M[:i] * L[:i])
            + sum(G[i:] * L[i:]) - G[i] * sum(L[i:])
        ) / 10000)
        for i in range(len(df_live))
    ]

    return df_live

# =================================================
# MERGE LIVE DATA
# =================================================
oc = fetch_live_oc()

if oc:
    live_df = compute_live_snapshot(oc, SELECTED)
    now = ist_hhmm()

    final = final.merge(
        live_df[[
            "Strike","MP_live",
            "CE IV L","CE Delta L","CE Gamma L","CE Vega L",
            "PE IV L","PE Delta L","PE Gamma L","PE Vega L",
        ]],
        on="Strike",
        how="inner",
    )

    final[f"MP ({now})"] = final["MP_live"]
    final[f"Δ MP (Live − {t1})"] = final[f"MP ({now})"] - final[f"MP ({t1})"]
    final["ΔΔ MP"] = (final[f"Δ MP (Live − {t1})"] - final[f"Δ MP (Live − {t1})"].shift(1))

    
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
cols = [
    "Strike",
    f"MP ({now})",
    f"MP ({t1})",
    f"Δ MP (Live − {t1})",
    "ΔΔ MP",
    f"MP ({t2})",
    f"Δ MP (T1 − T2)",

    # ---- IV ----
    "CE IV Δ",
    "PE IV Δ",

    # ---- GAMMA ----
    "CE Gamma Δ",
    "PE Gamma Δ",

    # ---- DELTA ----
    "CE Delta Δ",
    "PE Delta Δ",

    # ---- VEGA ----
    "CE Vega Δ",
    "PE Vega Δ",
]


final = final[cols].sort_values("Strike").round(0)

st.dataframe(final, use_container_width=True, height=750)

st.caption(
    "Strike set identical to collector | 25 below + 26 above | "
    "Δ = Live − T1 | IV & Greeks ×10000"
)

