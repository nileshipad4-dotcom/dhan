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
CENTER = UNDERLYINGS[UNDERLYING]["center"]

# =================================================
# LOAD HISTORICAL CSV
# =================================================
try:
    df = pd.read_csv(CSV_PATH)
except Exception:
    st.error("❌ CSV not found. Run collector.py first.")
    st.stop()

required_cols = [
    "Strike","CE LTP","CE OI","CE IV","CE Delta","CE Gamma","CE Vega",
    "PE LTP","PE OI","PE IV","PE Delta","PE Gamma","PE Vega",
    "timestamp","Max Pain"
]

missing = [c for c in required_cols if c not in df.columns]
if missing:
    st.error(f"❌ CSV schema mismatch. Missing columns: {missing}")
    st.stop()

df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce").astype(int)
df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
df["timestamp"] = df["timestamp"].astype(str).str[-5:]

# =================================================
# STRIKE WINDOW (IDENTICAL TO COLLECTOR)
# =================================================
all_strikes = sorted(df["Strike"].unique())
below = [s for s in all_strikes if s <= CENTER][-25:]
above = [s for s in all_strikes if s > CENTER][:26]
STRIKES = set(below + above)

df = df[df["Strike"].isin(STRIKES)]

# =================================================
# TIME SELECTION
# =================================================
times = sorted(df["timestamp"].unique(), reverse=True)
if len(times) < 2:
    st.error("❌ Need at least 2 timestamps in CSV")
    st.stop()

t1 = st.selectbox("Time-1 (Latest)", times, 0)
t2 = st.selectbox("Time-2 (Previous)", times, 1)

# =================================================
# HISTORICAL MAX PAIN (÷100)
# =================================================
mp_t1 = df[df["timestamp"] == t1].groupby("Strike")["Max Pain"].mean() / 100
mp_t2 = df[df["timestamp"] == t2].groupby("Strike")["Max Pain"].mean() / 100

final = pd.DataFrame({
    "Strike": mp_t1.index,
    f"MP ({t1})": mp_t1.values,
    f"MP ({t2})": mp_t2.reindex(mp_t1.index).values,
})

final["Δ MP (T1 − T2)"] = final[f"MP ({t1})"] - final[f"MP ({t2})"]

# =================================================
# T1 BASE (IV + GREEKS)
# =================================================
t1_base = (
    df[df["timestamp"] == t1]
    .groupby("Strike", as_index=False)
    .mean(numeric_only=True)
    .rename(columns={
        "CE IV": "CE_IV_T1",
        "PE IV": "PE_IV_T1",
        "CE Gamma": "CE_Gamma_T1",
        "PE Gamma": "PE_Gamma_T1",
        "CE Delta": "CE_Delta_T1",
        "PE Delta": "PE_Delta_T1",
        "CE Vega": "CE_Vega_T1",
        "PE Vega": "PE_Vega_T1",
    })
)

final = final.merge(t1_base, on="Strike", how="inner")

# =================================================
# LIVE OPTION CHAIN (SAFE)
# =================================================
@st.cache_data(ttl=30)
def fetch_live_oc():
    cfg = UNDERLYINGS[UNDERLYING]

    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"]},
        timeout=10,
    )
    if r.status_code != 200:
        return None

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
        timeout=10,
    )
    if r.status_code != 200:
        return None

    return r.json().get("data", {}).get("oc")

# =================================================
# LIVE SNAPSHOT
# =================================================
oc = fetch_live_oc()
now = ist_hhmm()

if not oc:
    st.warning("⚠️ Live option chain unavailable (market closed / API issue)")
else:
    rows = []
    for s in STRIKES:
        v = oc.get(f"{float(s):.6f}", {})
        ce, pe = v.get("ce", {}), v.get("pe", {})

        rows.append({
            "Strike": s,
            "CE LTP": ce.get("last_price", 0),
            "CE OI": ce.get("oi", 0),
            "PE LTP": pe.get("last_price", 0),
            "PE OI": pe.get("oi", 0),

            "CE IV L": ce.get("implied_volatility"),
            "PE IV L": pe.get("implied_volatility"),
            "CE Gamma L": ce.get("greeks", {}).get("gamma"),
            "PE Gamma L": pe.get("greeks", {}).get("gamma"),
            "CE Delta L": ce.get("greeks", {}).get("delta"),
            "PE Delta L": pe.get("greeks", {}).get("delta"),
            "CE Vega L": ce.get("greeks", {}).get("vega"),
            "PE Vega L": pe.get("greeks", {}).get("vega"),
        })

    live = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

    # ---- LIVE MAX PAIN (÷100) ----
    A, B = live["CE LTP"], live["CE OI"]
    G, L, M = live["Strike"], live["PE OI"], live["PE LTP"]

    live["MP_live"] = [
        int((( 
            -sum(A[i:] * B[i:])
            + G[i] * sum(B[:i]) - sum(G[:i] * B[:i])
            - sum(M[:i] * L[:i])
            + sum(G[i:] * L[i:]) - G[i] * sum(L[i:])
        ) / 10000) / 100)
        for i in range(len(live))
    ]

    final = final.merge(live, on="Strike", how="inner")

    final[f"MP ({now})"] = final["MP_live"]
    final[f"Δ MP (Live − {t1})"] = final[f"MP ({now})"] - final[f"MP ({t1})"]
    final["ΔΔ MP"] = final[f"Δ MP (Live − {t1})"] - final[f"Δ MP (Live − {t1})"].shift(1)

    # ---- GREEKS Δ ----
    final["CE IV Δ"]    = (final["CE IV L"]    - final["CE_IV_T1"]) * FACTOR
    final["PE IV Δ"]    = (final["PE IV L"]    - final["PE_IV_T1"]) * FACTOR
    final["CE Gamma Δ"] = (final["CE Gamma L"] - final["CE_Gamma_T1"]) * FACTOR
    final["PE Gamma Δ"] = (final["PE Gamma L"] - final["PE_Gamma_T1"]) * FACTOR
    final["CE Delta Δ"] = (final["CE Delta L"] - final["CE_Delta_T1"]) * FACTOR
    final["PE Delta Δ"] = (final["PE Delta L"] - final["PE_Delta_T1"]) * FACTOR
    final["CE Vega Δ"]  = (final["CE Vega L"]  - final["CE_Vega_T1"]) * FACTOR
    final["PE Vega Δ"]  = (final["PE Vega L"]  - final["PE_Vega_T1"]) * FACTOR

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
    "Δ MP (T1 − T2)",
    "CE IV Δ","PE IV Δ",
    "CE Gamma Δ","PE Gamma Δ",
    "CE Delta Δ","PE Delta Δ",
    "CE Vega Δ","PE Vega Δ",
]

final = final[cols]

for c in final.columns:
    if "MP" in c:
        final[c] = final[c].astype("Int64")
    elif "Δ" in c:
        final[c] = final[c].round(1)

min_strike = final.loc[final[f"MP ({now})"].idxmin(), "Strike"]

def highlight(row):
    return [
        "background-color:#8B0000;color:white" if row["Strike"] == min_strike else ""
        for _ in row
    ]

freeze_upto = final.columns.tolist().index("ΔΔ MP") + 1

st.dataframe(
    final.style.apply(highlight, axis=1),
    use_container_width=True,
    height=750,
    column_config={
        c: st.column_config.NumberColumn(c, pinned=(i < freeze_upto))
        for i, c in enumerate(final.columns)
    },
)

st.caption(
    "25 below + 26 above | MP ÷100 | Greeks ×10000 | "
    "Δ = Live − T1 | ΔΔ = strike slope | Red = Min Live MP"
)
