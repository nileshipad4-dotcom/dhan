

import streamlit as st
import pandas as pd
import requests
import yfinance as yf
from datetime import datetime, timedelta

# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(layout="wide")
st.title("📊 NIFTY & BANKNIFTY – Max Pain")

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

def safe_spot(all_strikes, spot):
    if spot is None or pd.isna(spot):
        return all_strikes[len(all_strikes) // 2]
    return spot

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
# OPTION CHAIN
# =================================================
@st.cache_data(ttl=30)
def fetch_live_oc(cfg):
    try:
        exp = requests.post(
            f"{API_BASE}/optionchain/expirylist",
            headers=HEADERS,
            json={"UnderlyingScrip": cfg["scrip"], "UnderlyingSeg": cfg["seg"]},
            timeout=5,
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
            timeout=5,
        ).json().get("data", {}).get("oc")
    except Exception:
        return None

# =================================================
# BUILD TABLE (BULLETPROOF)
# =================================================
def build_table(cfg, spot_price):
    df = pd.read_csv(cfg["csv"])

    df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
    df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")
    df["timestamp"] = df["timestamp"].astype(str).str[-5:]

    df = df.dropna(subset=["Strike", "Max Pain"])

    all_strikes = sorted(df["Strike"].unique())

    if len(all_strikes) == 0:
        return pd.DataFrame(), ist_hhmm()

    spot = safe_spot(all_strikes, spot_price)

    STRIKES = set(
        [s for s in all_strikes if s <= spot][-25:]
        + [s for s in all_strikes if s > spot][:26]
    )

    df = df[df["Strike"].isin(STRIKES)]

    times = sorted(df["timestamp"].unique(), reverse=True)

    t1 = times[0]
    t2 = times[1] if len(times) > 1 else times[0]

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
        for s in STRIKES:
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
# DISPLAY
# =================================================
col1, col2 = st.columns(2)

for col, name in zip([col1, col2], ["NIFTY", "BANKNIFTY"]):
    cfg = UNDERLYINGS[name]
    spot_price = get_yahoo_price(cfg["yahoo"])
    table, now = build_table(cfg, spot_price)

    with col:
        st.subheader(f"{name} | Live Price: {int(spot_price) if spot_price else 'N/A'}")

        if table.empty:
            st.warning("No data available")
            continue

        min_strike = table.loc[table[f"MP ({now})"].idxmin(), "Strike"]

        def highlight(row):
            return [
                "background-color:#8B0000;color:white"
                if row["Strike"] == min_strike else ""
                for _ in row
            ]

        freeze_upto = table.columns.tolist().index("ΔΔ MP") + 1

        st.dataframe(
            table.style.apply(highlight, axis=1),
            use_container_width=True,
            height=700,
            column_config={
                c: st.column_config.NumberColumn(c, pinned=(i < freeze_upto))
                for i, c in enumerate(table.columns)
            },
        )
