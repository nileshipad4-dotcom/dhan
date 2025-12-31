import streamlit as st
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=60_000, key="auto_refresh")

FACTOR = 1000
STRIKE_RANGE = 10

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 INDEX")

# =================================================
# HELPERS
# =================================================
def ist_hhmm():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M")

@st.cache_data(ttl=30)
def get_yahoo_price(symbol):
    try:
        data = yf.Ticker(symbol).history(period="1d", interval="1m")
        return float(data["Close"].iloc[-1]) if not data.empty else None
    except Exception:
        return None

def atm_slice(df, spot, n=STRIKE_RANGE):
    if df.empty or spot is None:
        return df
    atm = min(df["Strike"], key=lambda x: abs(x - spot))
    idx = df.index[df["Strike"] == atm][0]
    return df.iloc[max(0, idx-n): idx+n+1].reset_index(drop=True)

def get_spot_band(strikes, spot):
    if spot is None:
        return set()
    lower = max([s for s in strikes if s <= spot], default=None)
    upper = min([s for s in strikes if s > spot], default=None)
    return {lower, upper}

# =================================================
# CONFIG
# =================================================
API_BASE = "https://api.dhan.co/v2"

HEADERS = {
    "client-id": "1102712380",
    "access-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY3MjM0NDg5LCJpYXQiOjE3NjcxNDgwODksInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.T2icHFBVwPloEVFQQ67s4Fh9Yj8HaAru3GzZgcAdIzauwvBSSztenwz0tZudegfoA5-DhFU7FX37dN5NhCXS8A",
    "Content-Type": "application/json",
}


CFG = {
    "NIFTY": {
        "scrip": 13,
        "seg": "IDX_I",
        "csv": "data/nifty.csv",
        "yahoo": "^NSEI",
        "center": 26000,
    },
    "BANKNIFTY": {
        "scrip": 25,
        "seg": "IDX_I",
        "csv": "data/banknifty.csv",
        "yahoo": "^NSEBANK",
        "center": 60000,
    },
    "MIDCPNIFTY": {
        "scrip": 442,
        "seg": "IDX_I",
        "csv": "data/midcpnifty.csv",
        "yahoo": "NIFTY_MID_SELECT.NS",
        "center": 13600,
    },
}

# =================================================
# LOAD CSVs
# =================================================
df_n = pd.read_csv(CFG["NIFTY"]["csv"])
df_b = pd.read_csv(CFG["BANKNIFTY"]["csv"])
df_m = pd.read_csv(CFG["MIDCPNIFTY"]["csv"])

row_signature = (len(df_n), len(df_b), len(df_m))

if "last_row_signature" not in st.session_state:
    st.session_state.last_row_signature = row_signature
elif row_signature != st.session_state.last_row_signature:
    st.session_state.last_row_signature = row_signature
    st.rerun()

for df in (df_n, df_b, df_m):
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"], errors="coerce")
        .dt.strftime("%Y-%m-%d %H:%M")
    )

common_times = sorted(
    set(df_n["timestamp"])
    .intersection(df_b["timestamp"])
    .intersection(df_m["timestamp"]),
    reverse=True,
)

# =================================================
# TIMESTAMP SELECTION
# =================================================
st.subheader("⏱ Timestamp Selection")

t1_full = st.selectbox("Time-1 (Latest)", common_times, index=0)
t2_full = st.selectbox(
    "Time-2 (Previous)",
    common_times,
    index=1 if len(common_times) > 1 else 0
)

t1 = t1_full[-5:]  # HH:MM only (for column names)
t2 = t2_full[-5:]

now = ist_hhmm()

# =================================================
# OPTION CHAIN
# =================================================
@st.cache_data(ttl=30)
def fetch_live_oc(cfg):
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
        json={
            "UnderlyingScrip": cfg["scrip"],
            "UnderlyingSeg": cfg["seg"],
            "Expiry": exp[0],
        },
    ).json().get("data", {}).get("oc")

# =================================================
# MAX PAIN
# =================================================
def build_max_pain(cfg):
    df = pd.read_csv(cfg["csv"])
    df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
    df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"], errors="coerce")
        .dt.strftime("%Y-%m-%d %H:%M")
    )
    df = df.dropna(subset=["Strike", "Max Pain"])

    strikes = sorted(df["Strike"].unique())
    center = cfg["center"]

    below = [s for s in strikes if s <= center][-35:]
    above = [s for s in strikes if s > center][:36]
    strikes = sorted(set(below + above))

    df = df[df["Strike"].isin(strikes)]

    mp1 = (
        df[df["timestamp"] == t1_full]
        .groupby("Strike")["Max Pain"].mean() / 100
    )

    mp2 = (
        df[df["timestamp"] == t2_full]
        .groupby("Strike")["Max Pain"].mean() / 100
    )

    final = pd.DataFrame({
        "Strike": mp1.index,
        f"MP ({now})": None,
        f"MP ({t1})": mp1.values,
        f"MP ({t2})": mp2.reindex(mp1.index).values,
    })

    oc = fetch_live_oc(cfg)
    if oc:
        rows = []
        for s in strikes:
            v = oc.get(f"{float(s):.6f}", {})
            rows.append({
                "Strike": s,
                "CE LTP": v.get("ce", {}).get("last_price", 0),
                "CE OI": v.get("ce", {}).get("oi", 0),
                "PE LTP": v.get("pe", {}).get("last_price", 0),
                "PE OI": v.get("pe", {}).get("oi", 0),
            })

        live = pd.DataFrame(rows).sort_values("Strike")

        A, B = live["CE LTP"], live["CE OI"]
        G, L, M = live["Strike"], live["PE OI"], live["PE LTP"]

        final[f"MP ({now})"] = [
            ((-sum(A[i:] * B[i:])
              + G.iloc[i] * sum(B[:i]) - sum(G[:i] * B[:i])
              - sum(M[:i] * L[:i])
              + sum(G[i:] * L[i:]) - G.iloc[i] * sum(L[i:])
             ) / 10000) / 100
            for i in range(len(live))
        ]

    final[f"Δ MP ({now}−{t1})"] = final[f"MP ({now})"] - final[f"MP ({t1})"]
    final[f"Δ MP ({t1}−{t2})"] = final[f"MP ({t1})"] - final[f"MP ({t2})"]
    final["ΔΔ MP"] = final[f"Δ MP ({now}−{t1})"].diff()

    return final.round(0).astype("Int64").reset_index(drop=True)

# =================================================
# DISPLAY MAX PAIN
# =================================================
st.divider()
st.subheader("📌 MAX PAIN")

c1, c2, c3 = st.columns(3)

for col, name in zip([c1, c2, c3], ["NIFTY", "BANKNIFTY", "MIDCPNIFTY"]):
    cfg = CFG[name]
    table_full = build_max_pain(cfg)
    spot = get_yahoo_price(cfg["yahoo"])
    table = atm_slice(table_full, spot)

    band = get_spot_band(table["Strike"].tolist(), spot)
    min_strike = table.loc[table[f"MP ({now})"].idxmin(), "Strike"]

    with col:
        st.markdown(f"### {name} : {int(spot) if spot else 'N/A'}")

        def highlight_mp(row):
            if row["Strike"] == min_strike:
                return ["background-color:#8B0000;color:white"] * len(row)
            if row["Strike"] in band:
                return ["background-color:#00008B;color:white"] * len(row)
            return [""] * len(row)

        st.dataframe(
            table.style.apply(highlight_mp, axis=1),
            use_container_width=True,
            height=600,
        )

# =================================================
# IV COMPARISON (UNCHANGED)
# =================================================
st.divider()
st.subheader("📌 IV COMPARISON")

col4, col5 = st.columns(2)

for col, name in zip([col4, col5], ["NIFTY", "BANKNIFTY"]):
    cfg = CFG[name]
    spot = get_yahoo_price(cfg["yahoo"])
    iv = build_iv_table(cfg, spot)
    band = get_spot_band(iv["Strike"].tolist(), spot)

    with col:
        st.markdown(f"### {name} : {int(spot) if spot else 'N/A'}")

        def highlight_iv(row):
            if row["Strike"] in band:
                return ["background-color:#00008B;color:white"] * len(row)
            return [""] * len(row)

        st.dataframe(
            iv.style.apply(highlight_iv, axis=1),
            use_container_width=True,
            height=600,
        )
