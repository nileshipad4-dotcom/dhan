

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import yfinance as yf


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

@st.cache_data(ttl=15)
def get_yahoo_price(index_name):
    try:
        if index_name == "NIFTY":
            t = yf.Ticker("^NSEI")
        else:  # BANKNIFTY
            t = yf.Ticker("^NSEBANK")

        price = t.fast_info["last_price"]
        return int(price)
    except Exception:
        return None

def compute_pcr(call_oi, put_oi, call_vol=None, put_vol=None):
    pcr_oi = (put_oi / call_oi) if call_oi else None
    pcr_vol = None
    if call_vol is not None and call_vol != 0:
        pcr_vol = put_vol / call_vol
    return pcr_oi, pcr_vol
# =================================================
# PCR FROM CSV (T1 & T2)
# =================================================
def pcr_from_csv(df_snap):
    call_oi = df_snap["CE OI"].sum()
    put_oi = df_snap["PE OI"].sum()
    call_vol = df_snap.get("CE Volume", pd.Series()).sum()
    put_vol = df_snap.get("PE Volume", pd.Series()).sum()
    return compute_pcr(call_oi, put_oi, call_vol, put_vol)

pcr_t1_oi, pcr_t1_vol = pcr_from_csv(df[df["timestamp"] == t1])
pcr_t2_oi, pcr_t2_vol = pcr_from_csv(df[df["timestamp"] == t2])


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
live_price = get_yahoo_price(UNDERLYING)

st.sidebar.metric(
    label=f"{UNDERLYING} Live Price (Yahoo)",
    value=str(live_price) if live_price else "N/A"
)

CSV_PATH = f"data/{UNDERLYING.lower()}.csv"

CENTER = UNDERLYINGS[UNDERLYING]["center"]

# =================================================
# LOAD CSV (HISTORICAL)
# =================================================
df = pd.read_csv(CSV_PATH)

df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce").astype(int)
df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
df["timestamp"] = df["timestamp"].astype(str).str[-5:]

# =================================================
# STRIKE WINDOW (IDENTICAL TO COLLECTOR)
# =================================================
all_strikes = sorted(df["Strike"].unique())
below = [s for s in all_strikes if s <= CENTER][-17:]
above = [s for s in all_strikes if s > CENTER][:18]
STRIKES = set(below + above)

df = df[df["Strike"].isin(STRIKES)]

# =================================================
# TIME SELECTION
# =================================================
times = sorted(df["timestamp"].unique(), reverse=True)
t1 = st.selectbox("Time-1 (Latest)", times, 0)
t2 = st.selectbox("Time-2 (Previous)", times, 1)

# =================================================
# HISTORICAL MAX PAIN
# =================================================
mp_t1 = df[df["timestamp"] == t1].groupby("Strike")["Max Pain"].mean() / 10
mp_t2 = df[df["timestamp"] == t2].groupby("Strike")["Max Pain"].mean() / 10

final = pd.DataFrame({
    f"MP ({t1})": mp_t1,
    f"MP ({t2})": mp_t2,
}).reset_index()

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
        "CE Delta": "CE_Delta_T1",
        "CE Gamma": "CE_Gamma_T1",
        "CE Vega": "CE_Vega_T1",
        "PE IV": "PE_IV_T1",
        "PE Delta": "PE_Delta_T1",
        "PE Gamma": "PE_Gamma_T1",
        "PE Vega": "PE_Vega_T1",
    })
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
oc = fetch_live_oc()
now = ist_hhmm()

if oc:
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
            "CE Delta L": ce.get("greeks", {}).get("delta"),
            "CE Gamma L": ce.get("greeks", {}).get("gamma"),
            "CE Vega L": ce.get("greeks", {}).get("vega"),

            "PE IV L": pe.get("implied_volatility"),
            "PE Delta L": pe.get("greeks", {}).get("delta"),
            "PE Gamma L": pe.get("greeks", {}).get("gamma"),
            "PE Vega L": pe.get("greeks", {}).get("vega"),
        })

    # ---------------------------------------------
    # LIVE DATAFRAME
    # ---------------------------------------------
    live_df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

    # ---------------------------------------------
    # LIVE PCR (FROM LIVE OPTION CHAIN)
    # ---------------------------------------------
    call_oi_live = live_df["CE OI"].sum()
    put_oi_live = live_df["PE OI"].sum()

    # Volume may not exist → safe fallback
    call_vol_live = live_df.get("CE Volume", pd.Series(dtype=float)).sum()
    put_vol_live = live_df.get("PE Volume", pd.Series(dtype=float)).sum()

    pcr_live_oi, pcr_live_vol = compute_pcr(
        call_oi_live,
        put_oi_live,
        call_vol_live,
        put_vol_live,
    )

    # ---------------------------------------------
    # PCR TABLE (LIVE vs T1 vs T2)
    # ---------------------------------------------
    pcr_table = pd.DataFrame(
        {
            "Live": [pcr_live_oi, pcr_live_vol],
            t1: [pcr_t1_oi, pcr_t1_vol],
            t2: [pcr_t2_oi, pcr_t2_vol],
        },
        index=["PCR (OI)", "PCR (Volume)"],
    )

    st.subheader("📊 Put–Call Ratio Snapshot")
    st.dataframe(
        pcr_table.applymap(
            lambda x: f"{x:.3f}" if pd.notna(x) else "NA"
        ),
        use_container_width=True,
    )

    # ---------------------------------------------
    # LIVE MAX PAIN (MATCHES COLLECTOR)
    # ---------------------------------------------
    A, B = live_df["CE LTP"], live_df["CE OI"]
    G, L, M = live_df["Strike"], live_df["PE OI"], live_df["PE LTP"]

    live_df["MP_live"] = [
        int((
            -sum(A[i:] * B[i:])
            + G.iloc[i] * sum(B[:i]) - sum(G[:i] * B[:i])
            - sum(M[:i] * L[:i])
            + sum(G[i:] * L[i:]) - G.iloc[i] * sum(L[i:])
        ) / 10000 / 10)
        for i in range(len(live_df))
    ]

    final = final.merge(live_df, on="Strike", how="inner")

    final[f"MP ({now})"] = final["MP_live"]
    final[f"Δ MP (Live − {t1})"] = final[f"MP ({now})"] - final[f"MP ({t1})"]

    # ΔΔ MP (slope)
    final["ΔΔ MP"] = final[f"Δ MP (Live − {t1})"] - final[f"Δ MP (Live − {t1})"].shift(1)

    # IV + GREEKS Δ
    final["CE IV Δ"]    = (final["CE IV L"]    - final["CE_IV_T1"])    * FACTOR
    final["PE IV Δ"]    = (final["PE IV L"]    - final["PE_IV_T1"])    * FACTOR
    final["CE Gamma Δ"] = (final["CE Gamma L"] - final["CE_Gamma_T1"]) * FACTOR
    final["PE Gamma Δ"] = (final["PE Gamma L"] - final["PE_Gamma_T1"]) * FACTOR
    final["CE Delta Δ"] = (final["CE Delta L"] - final["CE_Delta_T1"]) * FACTOR
    final["PE Delta Δ"] = (final["PE Delta L"] - final["PE_Delta_T1"]) * FACTOR
    final["CE Vega Δ"]  = (final["CE Vega L"]  - final["CE_Vega_T1"])  * FACTOR
    final["PE Vega Δ"]  = (final["PE Vega L"]  - final["PE_Vega_T1"])  * FACTOR

# =================================================
# FORCE INTEGER FOR ALL MAX PAIN COLUMNS
# =================================================
for c in final.columns:
    if "MP" in c:   # catches MP(now), MP(t1), MP(t2), Δ MP, ΔΔ MP
        final[c] = pd.to_numeric(final[c], errors="coerce").fillna(0).astype(int)

# =================================================
# ROUND IV & GREEKS TO 1 DECIMAL
# =================================================
for c in final.columns:
    if any(k in c for k in ["IV", "Delta", "Gamma", "Vega"]):
        final[c] = pd.to_numeric(final[c], errors="coerce").round(1)


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

final = final[cols].round(0)

# =================================================
# STYLING
# =================================================
min_mp_strike = final.loc[final[f"MP ({now})"].idxmin(), "Strike"]

def highlight(row):
    styles = []
    for col in final.columns:
        if row["Strike"] == min_mp_strike:
            styles.append("background-color:#8B0000;color:white")
        else:
            styles.append("")
    return styles

styled = final.style.apply(highlight, axis=1)

st.dataframe(
    styled,
    use_container_width=True,
    height=750,
    column_config={
        c: st.column_config.NumberColumn(c, pinned=True)
        for c in final.columns[:5]  # freeze till ΔΔ MP
    },
)

st.caption(
    "Strike window identical to collector | "
    "Δ = Live − T1 | IV & Greeks ×10000 | "
    "Red row = Minimum Live Max Pain"
)
