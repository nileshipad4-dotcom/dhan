import streamlit as st
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta, time
from streamlit_autorefresh import st_autorefresh

# =================================================
# AUTO REFRESH
# =================================================
st_autorefresh(interval=60_000, key="auto_refresh")
STRIKE_RANGE = 10

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 INDEX – MAX PAIN")

# =================================================
# HELPERS
# =================================================
def ist_hhmm():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M")


@st.cache_data(ttl=30)
def get_yahoo_price(symbol):
    try:
        d = yf.Ticker(symbol).history(period="1d", interval="1m")
        return int(d["Close"].iloc[-1]) if not d.empty else None
    except:
        return None


def atm_slice(df, spot, n=STRIKE_RANGE):
    if df.empty or spot is None:
        return df
    atm = min(df["Strike"], key=lambda x: abs(x - spot))
    idx = df.index[df["Strike"] == atm][0]
    return df.iloc[max(0, idx-n):idx+n+1].reset_index(drop=True)


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
    "access-token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY3ODMxNzA0LCJpYXQiOjE3Njc3NDUzMDQsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.cNABkyWQ26WzvubzFqFNaNM0ahoV8ozWaYSJnkUbNyvF1sDsd3nOc0KMJM2wdcC9B9nHsXTyRFlkRFjTLKw4YQ",
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
# LOAD CSVs
# =================================================
dfs = {}
for k, cfg in CFG.items():
    df = pd.read_csv(cfg["csv"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce") \
                        .dt.strftime("%Y-%m-%d %H:%M")
    dfs[k] = df

# =================================================
# TIME FILTER (08:00–16:30)
# =================================================
def valid_time(ts):
    try:
        hh, mm = map(int, ts[-5:].split(":"))
        return time(8, 0) <= time(hh, mm) <= time(16, 30)
    except:
        return False

common_times = sorted(
    [t for t in set.intersection(*[set(dfs[k]["timestamp"]) for k in CFG]) if valid_time(t)],
    reverse=True
)

# =================================================
# TIMESTAMP SELECTION
# =================================================
st.subheader("⏱ Timestamp Selection")
t1_full = st.selectbox("Time-1 (Latest)", common_times, 0)
t2_full = st.selectbox("Time-2 (Previous)", common_times, 1)

t1 = t1_full[-5:]
t2 = t2_full[-5:]
now = ist_hhmm()

# =================================================
# LIVE OPTION CHAIN
# =================================================
@st.cache_data(ttl=30)
def fetch_live_oc(cfg):
    try:
        exp = requests.post(
            f"{API_BASE}/optionchain/expirylist",
            headers=HEADERS,
            json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"]},
        ).json().get("data", [])

        if not exp:
            return {}

        oc = requests.post(
            f"{API_BASE}/optionchain",
            headers=HEADERS,
            json={
                "UnderlyingScrip": cfg["scrip"],
                "UnderlyingSeg": cfg["seg"],
                "Expiry": exp[0],
            },
        ).json()

        return oc.get("data", {}).get("oc", {})
    except:
        return {}

# =================================================
# BUILD MAX PAIN
# =================================================
def build_max_pain(cfg):
    df = pd.read_csv(cfg["csv"])
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M")

    strikes = sorted(df["Strike"].unique())
    c = cfg["center"]

    strikes = sorted(set(
        [s for s in strikes if s <= c][-35:] +
        [s for s in strikes if s > c][:36]
    ))

    df = df[df["Strike"].isin(strikes)]

    mp1 = df[df["timestamp"] == t1_full].groupby("Strike")["Max Pain"].mean() / 100
    mp2 = df[df["timestamp"] == t2_full].groupby("Strike")["Max Pain"].mean() / 100

    final = pd.DataFrame({
        "Strike": mp1.index.astype(int),
        f"MP ({t1})": mp1.round(0).astype("Int64"),
        f"MP ({t2})": mp2.reindex(mp1.index).round(0).astype("Int64"),
    })

    oc = fetch_live_oc(cfg)

    rows = []
    for s in final["Strike"]:
        key = f"{int(s)}.000000"   # 🔥 FIXED KEY FORMAT
        v = oc.get(key, {})
        rows.append({
            "Strike": s,
            "CE OI": v.get("ce", {}).get("oi", 0),
            "CE Vol": v.get("ce", {}).get("volume", 0),
            "PE OI": v.get("pe", {}).get("oi", 0),
            "PE Vol": v.get("pe", {}).get("volume", 0),
            "CE LTP": v.get("ce", {}).get("last_price", 0),
            "PE LTP": v.get("pe", {}).get("last_price", 0),
        })

    live = pd.DataFrame(rows).set_index("Strike") \
            .reindex(final["Strike"]).fillna(0).reset_index()

    A, B = live["CE LTP"], live["CE OI"]
    G, L, M = live["Strike"], live["PE OI"], live["PE LTP"]

    final[f"MP ({now})"] = (
        (-A * B).cumsum()[::-1]
        + (G * B).cumsum()
        - (G * B).cumsum().shift(fill_value=0)
        - (M * L).cumsum()
        + (G * L).cumsum()[::-1]
        - (G * L).cumsum()[::-1].shift(fill_value=0)
    ) / 1_000_000

    final[f"MP ({now})"] = final[f"MP ({now})"].round(0).astype("Int64")

    final[f"Δ MP ({now}−{t1})"] = (final[f"MP ({now})"] - final[f"MP ({t1})"]).astype("Int64")
    final[f"Δ MP ({t1}−{t2})"] = (final[f"MP ({t1})"] - final[f"MP ({t2})"]).astype("Int64")

    t1_df = df[df["timestamp"] == t1_full].groupby("Strike").sum()
    t2_df = df[df["timestamp"] == t2_full].groupby("Strike").sum()

    def d(x): return (x / 10000).round(0).astype("Int64")

    final["Δ CE OI (Live−T1)"] = d(live["CE OI"] - t1_df["CE OI"].reindex(final["Strike"]))
    final["Δ PE OI (Live−T1)"] = d(live["PE OI"] - t1_df["PE OI"].reindex(final["Strike"]))
    final["Δ CE Vol (Live−T1)"] = d(live["CE Vol"] - t1_df["CE Volume"].reindex(final["Strike"]))
    final["Δ PE Vol (Live−T1)"] = d(live["PE Vol"] - t1_df["PE Volume"].reindex(final["Strike"]))

    final["Δ CE OI (T1−T2)"] = d(t1_df["CE OI"].reindex(final["Strike"]) - t2_df["CE OI"].reindex(final["Strike"]))
    final["Δ PE OI (T1−T2)"] = d(t1_df["PE OI"].reindex(final["Strike"]) - t2_df["PE OI"].reindex(final["Strike"]))
    final["Δ CE Vol (T1−T2)"] = d(t1_df["CE Volume"].reindex(final["Strike"]) - t2_df["CE Volume"].reindex(final["Strike"]))
    final["Δ PE Vol (T1−T2)"] = d(t1_df["PE Volume"].reindex(final["Strike"]) - t2_df["PE Volume"].reindex(final["Strike"]))

    return final

# =================================================
# DISPLAY
# =================================================
st.divider()
st.subheader("📌 MAX PAIN")

for name, cfg in CFG.items():
    table = atm_slice(build_max_pain(cfg), get_yahoo_price(cfg["yahoo"]))

    mp_col = f"MP ({now})"
    min_strike = table.loc[table[mp_col].idxmin(), "Strike"] \
        if mp_col in table and table[mp_col].notna().any() else None

    band = get_spot_band(table["Strike"].tolist(), get_yahoo_price(cfg["yahoo"]))

    st.markdown(f"## {name}")

    def style_row(row):
        styles = [""] * len(row)

        if min_strike is not None and row["Strike"] == min_strike:
            styles = ["background-color:#8B0000;color:white"] * len(row)
        elif row["Strike"] in band:
            styles = ["background-color:#00008B;color:white"] * len(row)

        cols = list(row.index)

        def pair(c1, c2):
            i1, i2 = cols.index(c1), cols.index(c2)
            if pd.isna(row[c1]) or pd.isna(row[c2]):
                return
            color = "#8B0000" if row[c1] > row[c2] else "#006400"
            styles[i1] = styles[i2] = f"background-color:{color};color:white"

        pair("Δ CE Vol (Live−T1)", "Δ PE Vol (Live−T1)")
        pair("Δ CE OI (Live−T1)", "Δ PE OI (Live−T1)")
        pair("Δ CE Vol (T1−T2)", "Δ PE Vol (T1−T2)")
        pair("Δ CE OI (T1−T2)", "Δ PE OI (T1−T2)")

        return styles

    st.dataframe(
        table.style.apply(style_row, axis=1),
        use_container_width=True,
        height=600,
    )

    st.divider()
