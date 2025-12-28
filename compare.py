

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 NIFTY / BANKNIFTY – Max Pain")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=360_000, key="refresh")
except Exception:
    pass

# =================================================
# HELPERS
# =================================================
def ist_hhmm():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M")

# =================================================
# CONFIG
# =================================================
API_BASE = "https://api.dhan.co/v2"

HEADERS = {
    "client-id": "1102712380",
    "access-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY3MDQyOTkyLCJpYXQiOjE3NjY5NTY1OTIsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.ZCr0-AzvUPMziokEvu2Gi0IX2_X8sA3LYpB7svs49p48Wz3Maf8_y60Sgu43157pGc7pL4x-s98MUjO9X6PKSA",
    "Content-Type": "application/json",
}


UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I", "center": 26000, "security_id": 256265},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I", "center": 60000, "security_id": 260105},
}

# =================================================
# LIVE INDEX PRICE
# =================================================
@st.cache_data(ttl=5)
def get_index_price(security_id):
    r = requests.post(
        f"{API_BASE}/marketfeed/ltp",
        headers=HEADERS,
        json={"NSE_IDX": [security_id]},
    )
    if r.status_code != 200:
        return None
    return r.json().get("data", {}).get(str(security_id), {}).get("ltp")

# =================================================
# SIDEBAR
# =================================================
UNDERLYING = st.sidebar.selectbox("Index", list(UNDERLYINGS.keys()))
CENTER = UNDERLYINGS[UNDERLYING]["center"]
CSV_PATH = f"data/{UNDERLYING.lower()}.csv"

live_price = get_index_price(UNDERLYINGS[UNDERLYING]["security_id"])
st.sidebar.metric(f"{UNDERLYING} Live Price", f"{int(live_price)}" if live_price else "N/A")

# =================================================
# LOAD CSV
# =================================================
df = pd.read_csv(CSV_PATH)
df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
df["timestamp"] = df["timestamp"].astype(str).str[-5:]

# =================================================
# STRIKE WINDOW
# =================================================
all_strikes = sorted(df["Strike"].dropna().unique())
STRIKES = set(
    [s for s in all_strikes if s <= CENTER][-25:]
    + [s for s in all_strikes if s > CENTER][:26]
)
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
mp_t1 = df[df["timestamp"] == t1].groupby("Strike")["Max Pain"].mean() / 100
mp_t2 = df[df["timestamp"] == t2].groupby("Strike")["Max Pain"].mean() / 100

final = pd.DataFrame({
    "Strike": mp_t1.index,
    f"MP ({t1})": mp_t1.values,
    f"MP ({t2})": mp_t2.reindex(mp_t1.index).values,
})

final["Δ MP (T1 − T2)"] = final[f"MP ({t1})"] - final[f"MP ({t2})"]

# =================================================
# LIVE OPTION CHAIN
# =================================================
@st.cache_data(ttl=30)
def fetch_live_oc():
    cfg = UNDERLYINGS[UNDERLYING]
    exp = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"]},
    ).json().get("data", [])
    if not exp:
        return None
    return requests.post(
        f"{API_BASE}/optionchain",
        headers=HEADERS,
        json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"], "Expiry": exp[0]},
    ).json().get("data", {}).get("oc")

oc = fetch_live_oc()
now = ist_hhmm()

if oc:
    rows = []
    for s in STRIKES:
        v = oc.get(f"{float(s):.6f}", {})
        rows.append({
            "Strike": s,
            "CE LTP": v.get("ce", {}).get("last_price", 0),
            "CE OI": v.get("ce", {}).get("oi", 0),
            "PE LTP": v.get("pe", {}).get("last_price", 0),
            "PE OI": v.get("pe", {}).get("oi", 0),
        })

    live = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

    A, B = live["CE LTP"], live["CE OI"]
    G, L, M = live["Strike"], live["PE OI"], live["PE LTP"]

    live["MP_live"] = [
        ((-sum(A[i:] * B[i:])
          + G.iloc[i] * sum(B[:i]) - sum(G[:i] * B[:i])
          - sum(M[:i] * L[:i])
          + sum(G[i:] * L[i:]) - G.iloc[i] * sum(L[i:])
         ) / 10000) / 100
        for i in range(len(live))
    ]

    final = final.merge(live[["Strike", "MP_live"]], on="Strike")
    final[f"MP ({now})"] = final["MP_live"]
    final[f"Δ MP (Live − {t1})"] = final[f"MP ({now})"] - final[f"MP ({t1})"]
    final["ΔΔ MP"] = final[f"Δ MP (Live − {t1})"].diff()

# =================================================
# FINAL VIEW — NO DECIMALS
# =================================================
cols = [
    "Strike",
    f"MP ({now})",
    f"MP ({t1})",
    f"Δ MP (Live − {t1})",
    "ΔΔ MP",
    f"MP ({t2})",
    "Δ MP (T1 − T2)",
]

final = final[cols].apply(pd.to_numeric, errors="coerce")
final = final.round(0).astype("Int64")

# =================================================
# DISPLAY
# =================================================
min_strike = final.loc[final[f"MP ({now})"].idxmin(), "Strike"]

def highlight(row):
    return ["background-color:#8B0000;color:white" if row["Strike"] == min_strike else "" for _ in row]

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

st.caption("Max Pain only | No decimals | Red = Min Live MP")
