
import streamlit as st
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta

FACTOR = 1000
STRIKE_RANGE = 10  # used only for IV tables (unchanged)

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 NIFTY & BANKNIFTY – Max Pain + IV Dashboard")

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

@st.cache_data(ttl=30)
def get_yahoo_price(symbol):
    try:
        data = yf.Ticker(symbol).history(period="1d", interval="1m")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception:
        return None

def atm_strikes(strikes, spot):
    if not strikes:
        return []
    if spot is None:
        mid = len(strikes) // 2
        return strikes[mid-STRIKE_RANGE:mid+STRIKE_RANGE+1]
    atm = min(strikes, key=lambda x: abs(x - spot))
    idx = strikes.index(atm)
    return strikes[max(0, idx-STRIKE_RANGE): idx+STRIKE_RANGE+1]

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
    "access-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY3MDQyOTkyLCJpYXQiOjE3NjY5NTY1OTIsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.ZCr0-AzvUPMziokEvu2Gi0IX2_X8sA3LYpB7svs49p48Wz3Maf8_y60Sgu43157pGc7pL4x-s98MUjO9X6PKSA",
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
}

# =================================================
# COMMON TIMESTAMPS
# =================================================
df_n = pd.read_csv(CFG["NIFTY"]["csv"])
df_b = pd.read_csv(CFG["BANKNIFTY"]["csv"])

for df in (df_n, df_b):
    df["timestamp"] = df["timestamp"].astype(str).str[-5:]

common_times = sorted(
    set(df_n["timestamp"]).intersection(df_b["timestamp"]),
    reverse=True,
)

st.subheader("⏱ Timestamp Selection")
t1 = st.selectbox("Time-1 (Latest)", common_times, index=0)
t2 = st.selectbox("Time-2 (Previous)", common_times, index=1 if len(common_times) > 1 else 0)
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
# MAX PAIN TABLE (FIXED TO MATCH COLLECTOR.PY)
# =================================================
def build_max_pain(cfg):
    df = pd.read_csv(cfg["csv"])
    df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
    df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
    df["timestamp"] = df["timestamp"].astype(str).str[-5:]
    df = df.dropna(subset=["Strike", "Max Pain"])

    # -------- STRIKE SET MATCHES collector.py --------
    all_strikes = sorted(df["Strike"].unique())
    center = cfg["center"]

    below = [s for s in all_strikes if s <= center][-35:]
    above = [s for s in all_strikes if s > center][:36]
    strikes = sorted(set(below + above))
    # -------------------------------------------------

    df = df[df["Strike"].isin(strikes)]

    mp1 = df[df["timestamp"] == t1].groupby("Strike")["Max Pain"].mean() / 100
    mp2 = df[df["timestamp"] == t2].groupby("Strike")["Max Pain"].mean() / 100

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

        live["MP_live"] = [
            ((-sum(A[i:] * B[i:])
              + G.iloc[i] * sum(B[:i]) - sum(G[:i] * B[:i])
              - sum(M[:i] * L[:i])
              + sum(G[i:] * L[i:]) - G.iloc[i] * sum(L[i:])
             ) / 10000) / 100
            for i in range(len(live))
        ]

        final = final.merge(live[["Strike", "MP_live"]], on="Strike", how="left")
        final[f"MP ({now})"] = final["MP_live"]

    final[f"Δ MP ({now}−{t1})"] = final[f"MP ({now})"] - final[f"MP ({t1})"]
    final[f"Δ MP ({t1}−{t2})"] = final[f"MP ({t1})"] - final[f"MP ({t2})"]
    final["ΔΔ MP"] = final[f"Δ MP ({now}−{t1})"].diff()

    final = final.drop(columns=["MP_live"], errors="ignore")
    final = final.round(0).astype("Int64").reset_index(drop=True)

    return final

# =================================================
# IV TABLE (UNCHANGED)
# =================================================
def build_iv_table(cfg, spot):
    df = pd.read_csv(cfg["csv"])
    df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
    df["CE IV"] = pd.to_numeric(df["CE IV"], errors="coerce")
    df["PE IV"] = pd.to_numeric(df["PE IV"], errors="coerce")
    df["timestamp"] = df["timestamp"].astype(str).str[-5:]

    strikes = atm_strikes(sorted(df["Strike"].dropna().unique()), spot)

    h1 = df[df["timestamp"] == t1].groupby("Strike").mean(numeric_only=True)
    h2 = df[df["timestamp"] == t2].groupby("Strike").mean(numeric_only=True)

    oc = fetch_live_oc(cfg)
    rows = []

    if not oc:
        return pd.DataFrame()

    for s in strikes:
        v = oc.get(f"{float(s):.6f}", {})
        ce = v.get("ce", {})
        pe = v.get("pe", {})

        rows.append({
            "Strike": s,
            f"CE IV Δ ({now}−{t1})": (ce.get("implied_volatility", 0) - h1.loc[s, "CE IV"]) * FACTOR if s in h1.index else None,
            f"CE IV Δ ({t1}−{t2})": (h1.loc[s, "CE IV"] - h2.loc[s, "CE IV"]) * FACTOR if s in h1.index and s in h2.index else None,
            f"PE IV Δ ({now}−{t1})": (pe.get("implied_volatility", 0) - h1.loc[s, "PE IV"]) * FACTOR if s in h1.index else None,
            f"PE IV Δ ({t1}−{t2})": (h1.loc[s, "PE IV"] - h2.loc[s, "PE IV"]) * FACTOR if s in h1.index and s in h2.index else None,
        })

    iv = pd.DataFrame(rows)
    iv = iv.apply(pd.to_numeric, errors="coerce")
    iv = iv.round(0).astype("Int64")
    return iv

# =================================================
# DISPLAY
# =================================================
st.divider()
st.subheader("📌 MAX PAIN")

col1, col2 = st.columns(2)

for col, name in zip([col1, col2], ["NIFTY", "BANKNIFTY"]):
    cfg = CFG[name]
    table = build_max_pain(cfg)
    spot = get_yahoo_price(cfg["yahoo"])
    band = get_spot_band(table["Strike"].tolist(), spot)
    min_strike = table.loc[table[f"MP ({now})"].idxmin(), "Strike"]

    with col:
        st.markdown(f"### {name} | Spot: {int(spot) if spot else 'N/A'}")

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

st.divider()
st.subheader("📌 IV COMPARISON")

col3, col4 = st.columns(2)

for col, name in zip([col3, col4], ["NIFTY", "BANKNIFTY"]):
    cfg = CFG[name]
    spot = get_yahoo_price(cfg["yahoo"])
    iv = build_iv_table(cfg, spot)
    band = get_spot_band(iv["Strike"].tolist(), spot)

    with col:
        st.markdown(f"### {name} | Spot: {int(spot) if spot else 'N/A'}")

        def highlight_iv(row):
            if row["Strike"] in band:
                return ["background-color:#00008B;color:white"] * len(row)
            return [""] * len(row)

        st.dataframe(
            iv.style.apply(highlight_iv, axis=1),
            use_container_width=True,
            height=600,
        )
