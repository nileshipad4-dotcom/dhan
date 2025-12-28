


import streamlit as st
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta

FACTOR = 1000

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 NIFTY & BANKNIFTY – Max Pain + IV Comparison")

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

def safe_spot(strikes, spot):
    return spot if spot is not None and not pd.isna(spot) else strikes[len(strikes)//2]

def get_spot_band(strikes, spot):
    if spot is None or pd.isna(spot):
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
    },
    "BANKNIFTY": {
        "scrip": 25,
        "seg": "IDX_I",
        "csv": "data/banknifty.csv",
        "yahoo": "^NSEBANK",
    },
}

# =================================================
# LOAD CSVs FOR COMMON TIMESTAMPS
# =================================================
df_n = pd.read_csv(CFG["NIFTY"]["csv"])
df_b = pd.read_csv(CFG["BANKNIFTY"]["csv"])

for df in (df_n, df_b):
    df["timestamp"] = df["timestamp"].astype(str).str[-5:]

common_times = sorted(
    set(df_n["timestamp"]).intersection(df_b["timestamp"]),
    reverse=True,
)

if not common_times:
    st.error("No common timestamps between NIFTY and BANKNIFTY")
    st.stop()

# =================================================
# TIMESTAMP SELECTOR (TOP)
# =================================================
st.subheader("⏱ Timestamp Selection")

t1 = st.selectbox("Time-1 (Latest)", common_times, index=0)
t2 = st.selectbox("Time-2 (Previous)", common_times, index=1 if len(common_times) > 1 else 0)

st.markdown(f"**Selected:** `{t1}` → `{t2}`")

# =================================================
# LIVE OPTION CHAIN
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
# MAX PAIN TABLE
# =================================================
def build_max_pain(cfg, spot, t1, t2):
    df = pd.read_csv(cfg["csv"])
    df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
    df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
    df["timestamp"] = df["timestamp"].astype(str).str[-5:]
    df = df.dropna(subset=["Strike", "Max Pain"])

    all_strikes = sorted(df["Strike"].unique())
    spot = safe_spot(all_strikes, spot)

    strikes = set(
        [s for s in all_strikes if s <= spot][-25:]
        + [s for s in all_strikes if s > spot][:26]
    )

    df = df[df["Strike"].isin(strikes)]

    mp_t1 = df[df["timestamp"] == t1].groupby("Strike")["Max Pain"].mean() / 100
    mp_t2 = df[df["timestamp"] == t2].groupby("Strike")["Max Pain"].mean() / 100

    final = pd.DataFrame({
        "Strike": mp_t1.index,
        f"MP ({t1})": mp_t1.values,
        f"MP ({t2})": mp_t2.reindex(mp_t1.index).values,
    })

    final[f"Δ MP (T1 − T2)"] = final[f"MP ({t1})"] - final[f"MP ({t2})"]

    oc = fetch_live_oc(cfg)
    now = ist_hhmm()

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

        final = final.merge(live[["Strike", "MP_live"]], on="Strike")
        final[f"MP ({now})"] = final["MP_live"]
        final[f"Δ MP (Live − {t1})"] = final[f"MP ({now})"] - final[f"MP ({t1})"]
        final["ΔΔ MP"] = final[f"Δ MP (Live − {t1})"].diff()

    cols = [
        "Strike",
        f"MP ({now})",
        f"MP ({t1})",
        f"MP ({t2})",
        f"Δ MP (Live − {t1})",
        f"Δ MP (T1 − T2)",
        "ΔΔ MP",
    ]

    final = final[cols].apply(pd.to_numeric, errors="coerce")
    final = final.round(0).astype("Int64").reset_index(drop=True)

    return final, now

# =================================================
# IV COMPARISON TABLE
# =================================================
def build_iv_table(cfg, spot):
    df = pd.read_csv(cfg["csv"])
    df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
    df["CE IV"] = pd.to_numeric(df["CE IV"], errors="coerce")
    df["PE IV"] = pd.to_numeric(df["PE IV"], errors="coerce")
    df["timestamp"] = df["timestamp"].astype(str).str[-5:]

    strikes = sorted(df["Strike"].dropna().unique())
    spot_band = get_spot_band(strikes, spot)

    h1 = df[df["timestamp"] == t1].groupby("Strike").mean(numeric_only=True)
    h2 = df[df["timestamp"] == t2].groupby("Strike").mean(numeric_only=True)

    oc = fetch_live_oc(cfg)
    rows = []

    if not oc:
        return pd.DataFrame(), spot_band

    for s in strikes:
        v = oc.get(f"{float(s):.6f}", {})
        ce = v.get("ce", {})
        pe = v.get("pe", {})

        rows.append({
            "Strike": s,
            "CE IV Δ (Live−T1)": (ce.get("implied_volatility", 0) - h1.loc[s, "CE IV"]) * FACTOR if s in h1.index else None,
            "CE IV Δ (T1−T2)": (h1.loc[s, "CE IV"] - h2.loc[s, "CE IV"]) * FACTOR if s in h1.index and s in h2.index else None,
            "PE IV Δ (Live−T1)": (pe.get("implied_volatility", 0) - h1.loc[s, "PE IV"]) * FACTOR if s in h1.index else None,
            "PE IV Δ (T1−T2)": (h1.loc[s, "PE IV"] - h2.loc[s, "PE IV"]) * FACTOR if s in h1.index and s in h2.index else None,
        })

    iv = pd.DataFrame(rows).round(1)
    return iv, spot_band

# =================================================
# DISPLAY
# =================================================
st.divider()
st.subheader("📌 MAX PAIN")

col1, col2 = st.columns(2)

for col, name in zip([col1, col2], ["NIFTY", "BANKNIFTY"]):
    cfg = CFG[name]
    spot = get_yahoo_price(cfg["yahoo"])
    table, now = build_max_pain(cfg, spot, t1, t2)

    with col:
        st.markdown(f"### {name} | Spot: {int(spot) if spot else 'N/A'}")

        band = get_spot_band(table["Strike"].tolist(), spot)
        min_strike = table.loc[table[f"MP ({now})"].idxmin(), "Strike"]

        def highlight_mp(row):
            if row["Strike"] == min_strike:
                return ["background-color:#8B0000;color:white"] * len(row)
            if row["Strike"] in band:
                return ["background-color:#00008B;color:white"] * len(row)
            return [""] * len(row)

        st.dataframe(table.style.apply(highlight_mp, axis=1), use_container_width=True, height=650)

st.divider()
st.subheader("📌 IV COMPARISON")

col3, col4 = st.columns(2)

for col, name in zip([col3, col4], ["NIFTY", "BANKNIFTY"]):
    cfg = CFG[name]
    spot = get_yahoo_price(cfg["yahoo"])
    iv, band = build_iv_table(cfg, spot)

    with col:
        st.markdown(f"### {name} | Spot: {int(spot) if spot else 'N/A'}")

        def highlight_iv(row):
            if row["Strike"] in band:
                return ["background-color:#00008B;color:white"] * len(row)
            return [""] * len(row)

        st.dataframe(iv.style.apply(highlight_iv, axis=1), use_container_width=True, height=650)
