# collector.py

import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# ================= CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY3NzQ2MjQ3LCJpYXQiOjE3Njc2NTk4NDcsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.q9mBbhk-ZSrh6-cY2dCN_31HsSPcfq3DXFpBxt6FxUpgFXxhBtdSR5eumlhsHKwu-UIcgv8R6gavs4OSfkEu2w"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY":      {"scrip": 13,  "seg": "IDX_I", "center": 26000},
    "BANKNIFTY":  {"scrip": 25,  "seg": "IDX_I", "center": 60000},
    "MIDCPNIFTY": {"scrip": 442, "seg": "IDX_I", "center": 13600},
    "SENSEX":     {"scrip": 51,  "seg": "IDX_I", "center": 84000},
}

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json",
}

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ================= BASE CSV =================
BASE_COLUMNS = [
    "Strike",

    "CE LTP","CE OI","CE Volume","CE IV","CE Delta","CE Gamma","CE Vega",
    "PE LTP","PE OI","PE Volume","PE IV","PE Delta","PE Gamma","PE Vega",

    "timestamp",
    "Max Pain",
]

for sym in ["nifty", "banknifty", "midcpnifty", "sensex"]:
    path = os.path.join(DATA_DIR, f"{sym}.csv")
    if not os.path.exists(path):
        pd.DataFrame(columns=BASE_COLUMNS).to_csv(path, index=False)

# ================= API FUNCTIONS =================
def get_expiries(scrip, seg):
    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={
            "UnderlyingScrip": scrip,
            "UnderlyingSeg": seg
        }
    )
    if r.status_code == 200:
        return r.json().get("data", [])
    return []


def get_option_chain(scrip, seg, expiry):
    r = requests.post(
        f"{API_BASE}/optionchain",
        headers=HEADERS,
        json={
            "UnderlyingScrip": scrip,
            "UnderlyingSeg": seg,
            "Expiry": expiry
        }
    )
    if r.status_code == 200:
        return r.json().get("data")
    return None


# ================= MAX PAIN =================
def compute_max_pain(df):
    A = df["CE LTP"].fillna(0)
    B = df["CE OI"].fillna(0)
    G = df["Strike"]
    M = df["PE LTP"].fillna(0)
    L = df["PE OI"].fillna(0)

    mp = []
    for i in range(len(df)):
        val = (
            -sum(A[i:] * B[i:])
            + G.iloc[i] * sum(B[:i]) - sum(G[:i] * B[:i])
            - sum(M[:i] * L[:i])
            + sum(G[i:] * L[i:]) - G.iloc[i] * sum(L[i:])
        )
        mp.append(int(val / 10000))

    df["Max Pain"] = mp
    return df


# ================= MAIN =================
def main():

    ts = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M")

    for sym, cfg in UNDERLYINGS.items():

        expiries = get_expiries(cfg["scrip"], cfg["seg"])
        if not expiries:
            continue

        data = get_option_chain(cfg["scrip"], cfg["seg"], expiries[0])
        if not data:
            continue

        oc = data.get("oc", {})
        if not oc:
            continue

        strikes = sorted(float(s) for s in oc.keys())

        center = cfg["center"]
        below = [s for s in strikes if s <= center][-35:]
        above = [s for s in strikes if s > center][:36]
        selected = sorted(set(below + above))

        rows = []

        for s in selected:
            v = oc.get(f"{s:.6f}", {})
            ce = v.get("ce", {})
            pe = v.get("pe", {})

            rows.append({
                "Strike": int(s),

                "CE LTP": ce.get("last_price"),
                "CE OI": ce.get("oi"),
                "CE Volume": ce.get("volume"),
                "CE IV": ce.get("implied_volatility"),
                "CE Delta": ce.get("greeks", {}).get("delta"),
                "CE Gamma": ce.get("greeks", {}).get("gamma"),
                "CE Vega": ce.get("greeks", {}).get("vega"),

                "PE LTP": pe.get("last_price"),
                "PE OI": pe.get("oi"),
                "PE Volume": pe.get("volume"),
                "PE IV": pe.get("implied_volatility"),
                "PE Delta": pe.get("greeks", {}).get("delta"),
                "PE Gamma": pe.get("greeks", {}).get("gamma"),
                "PE Vega": pe.get("greeks", {}).get("vega"),

                "timestamp": ts,
            })

        if not rows:
            continue

        df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

        # FORCE NUMERIC
        num_cols = [
            "CE LTP","CE OI","CE Volume","CE IV","CE Delta","CE Gamma","CE Vega",
            "PE LTP","PE OI","PE Volume","PE IV","PE Delta","PE Gamma","PE Vega"
        ]

        for c in num_cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        # MAX PAIN
        df = compute_max_pain(df)

        # COLUMN ORDER LOCK
        df = df[BASE_COLUMNS]

        out = os.path.join(DATA_DIR, f"{sym.lower()}.csv")
        df.to_csv(out, mode="a", header=not os.path.exists(out), index=False)

        print(f"[OK] {sym} saved @ {ts}")


if __name__ == "__main__":
    main()
