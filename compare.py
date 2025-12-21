import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# -------------------------------------------------
# PAGE CONFIG
# -------------------------------------------------
st.set_page_config(layout="wide")
st.title("📊 NIFTY / BANKNIFTY Max Pain Comparison (Live + Historical)")

# -------------------------------------------------
# AUTO REFRESH (60s)
# -------------------------------------------------
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60 * 1000, key="refresh")
except Exception:
    pass

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def ist_now_hhmm():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M")

def rotated_time_sort(times, pivot="09:15"):
    pivot_min = int(pivot[:2]) * 60 + int(pivot[3:])
    def key(t):
        h, m = map(int, t.split(":"))
        return ((h * 60 + m) - pivot_min) % (24 * 60)
    return sorted(times, key=key, reverse=True)

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I"},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I"},
}

HEADERS = {
    "client-id": "1102712380",
    "access-token": "YOUR_DHAN_TOKEN",  # use env var in production
    "Content-Type": "application/json",
}

UNDERLYING = st.sidebar.selectbox("Index", ["NIFTY", "BANKNIFTY"])
CSV_PATH = f"data/{UNDERLYING.lower()}.csv"

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

t1 = st.selectbox("Time-1 (Latest)", timestamps, index=0)
t2 = st.selectbox("Time-2 (Previous)", timestamps, index=1)

# -------------------------------------------------
# HISTORICAL MAX PAIN
# -------------------------------------------------
mp_t1 = (
    df[df["timestamp"] == t1]
    .groupby("Strike", as_index=False)["Max Pain"]
    .sum()
    .rename(columns={"Max Pain": f"MP ({t1})"})
)

mp_t2 = (
    df[df["timestamp"] == t2]
    .groupby("Strike", as_index=False)["Max Pain"]
    .sum()
    .rename(columns={"Max Pain": f"MP ({t2})"})
)

merged = mp_t1.merge(mp_t2, on="Strike", how="outer")
merged["△ MP (T1 − T2)"] = merged[f"MP ({t1})"] - merged[f"MP ({t2})"]

# -------------------------------------------------
# LIVE OPTION CHAIN (DHAN)
# -------------------------------------------------
@st.cache_data(ttl=30)
def fetch_live_chain(symbol):
    cfg = UNDERLYINGS[symbol]

    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"]},
        timeout=10,
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
        timeout=10,
    )
    return r.json().get("data")

# -------------------------------------------------
# LIVE MAX PAIN
# -------------------------------------------------
def compute_live_max_pain(oc):
    rows = []
    for strike, v in oc.items():
        ce = v.get("ce", {})
        pe = v.get("pe", {})

        rows.append({
            "Strike": float(strike),
            "CE LTP": ce.get("last_price", 0),
            "CE OI": ce.get("oi", 0),
            "PE LTP": pe.get("last_price", 0),
            "PE OI": pe.get("oi", 0),
        })

    df_live = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

    A = df_live["CE LTP"].values
    B = df_live["CE OI"].values
    G = df_live["Strike"].values
    L = df_live["PE OI"].values
    M = df_live["PE LTP"].values

    df_live["MP_live"] = [
        round(
            (
                -sum(A[i:] * B[i:])
                + G[i] * sum(B[:i])
                - sum(G[:i] * B[:i])
                - sum(M[:i] * L[:i])
                + sum(G[i:] * L[i:])
                - G[i] * sum(L[i:])
            ) / 10000
        )
        for i in range(len(df_live))
    ]

    return df_live[["Strike", "MP_live"]]

# -------------------------------------------------
# MERGE LIVE MP
# -------------------------------------------------
live_data = fetch_live_chain(UNDERLYING)

if live_data:
    now_ts = ist_now_hhmm()
    live_mp = compute_live_max_pain(live_data)

    merged = merged.merge(
        live_mp.rename(columns={"MP_live": f"MP ({now_ts})"}),
        on="Strike",
        how="left",
    )

    merged[f"△ MP (Live − {t1})"] = (
        merged[f"MP ({now_ts})"] - merged[f"MP ({t1})"]
    )

# -------------------------------------------------
# FINAL TABLE
# -------------------------------------------------
final_cols = ["Strike"]

if live_data:
    final_cols += [f"MP ({now_ts})", f"MP ({t1})", f"△ MP (Live − {t1})"]

final_cols += [f"MP ({t2})", "△ MP (T1 − T2)"]

final = merged[final_cols].sort_values("Strike").round(0)

# -------------------------------------------------
# DISPLAY
# -------------------------------------------------
st.subheader(f"{UNDERLYING} — Max Pain Comparison")

st.dataframe(
    final,
    use_container_width=True,
    height=700,
    column_config={
        "Strike": st.column_config.NumberColumn("Strike", pinned=True),
        **{c: st.column_config.NumberColumn(c, pinned=True) for c in final.columns if "MP (" in c},
    },
)

st.caption("MP = Max Pain | Live MP computed from real-time Dhan option chain")
