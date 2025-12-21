import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 NIFTY / BANKNIFTY – Max Pain Comparison")

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
df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
df["timestamp"] = df["timestamp"].astype(str).str[-5:]

# =================================================
# IDENTICAL STRIKE SELECTION (MATCHES COLLECTOR)
# =================================================
center = UNDERLYINGS[UNDERLYING]["center"]
all_strikes = sorted(df["Strike"].unique())

below = [s for s in all_strikes if s <= center][-25:]
above = [s for s in all_strikes if s > center][:26]
SELECTED_STRIKES = set(below + above)

df = df[df["Strike"].isin(SELECTED_STRIKES)]

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

final = mp_t1.merge(mp_t2, on="Strike", how="inner")
final[f"Δ MP (T1 − T2)"] = final[f"MP ({t1})"] - final[f"MP ({t2})"]

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
# LIVE MAX PAIN (IDENTICAL FORMULA)
# =================================================
def compute_live_max_pain(oc, strikes):
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

    return df_live[["Strike", "MP_live"]]

# =================================================
# MERGE LIVE MP
# =================================================
oc = fetch_live_oc()

if oc:
    live_mp = compute_live_max_pain(oc, SELECTED_STRIKES)
    now = ist_hhmm()

    final = final.merge(
        live_mp.rename(columns={"MP_live": f"MP ({now})"}),
        on="Strike",
        how="inner",
    )

    final[f"Δ MP (Live − {t1})"] = (
        final[f"MP ({now})"] - final[f"MP ({t1})"]
    )

# =================================================
# FINAL VIEW
# =================================================
cols = ["Strike"]

if oc:
    cols += [f"MP ({now})", f"MP ({t1})", f"Δ MP (Live − {t1})"]

cols += [f"MP ({t2})", f"Δ MP (T1 − T2)"]

final = final[cols].sort_values("Strike").round(0)

st.dataframe(final, use_container_width=True, height=750)

st.caption(
    "Strike set identical to collector | 25 below + 26 above | "
    "Δ = difference | Max Pain math fully aligned"
)
