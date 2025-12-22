# collector.py
import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# ================= CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "YOUR_TOKEN_HERE"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I", "center": 26000},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I", "center": 60000},
}

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json",
}

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ================= API =================
def get_expiries(scrip, seg):
    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": scrip, "UnderlyingSeg": seg},
    )
    return r.json().get("data", []) if r.status_code == 200 else []


def get_option_chain(scrip, seg, expiry):
    r = requests.post(
        f"{API_BASE}/optionchain",
        headers=HEADERS,
        json={"UnderlyingScrip": scrip, "UnderlyingSeg": seg, "Expiry": expiry},
    )
    return r.json().get("data") if r.status_code == 200 else None


# ================= MAX PAIN =================
def compute_max_pain(df):
    A = df["CE LTP"].fillna(0)
    B = df["CE OI"].fillna(0)
    G = df["Strike"]
    L = df["PE OI"].fillna(0)
    M = df["PE LTP"].fillna(0)

    mp = []
    for i in range(len(df)):
        mp.append(int((
            -sum(A[i:] * B[i:])
            + G[i] * sum(B[:i]) - sum(G[:i] * B[:i])
            - sum(M[:i] * L[:i])
            + sum(G[i:] * L[i:]) - G[i] * sum(L[i:])
        ) / 10000))

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
        below = [s for s in strikes if s <= center][-17:]
        above = [s for s in strikes if s > center][:18]
        selected = set(below + above)

        rows = []
        for s in selected:
            v = oc.get(f"{s:.6f}", {})
            ce, pe = v.get("ce", {}), v.get("pe", {})

            rows.append({
                "Strike": int(s),

                # ---------- CALL ----------
                "CE LTP": ce.get("last_price"),
                "CE OI": ce.get("oi"),
                "CE Volume": ce.get("volume"),        # ✅ ADDED
                "CE IV": ce.get("implied_volatility"),
                "CE Delta": ce.get("greeks", {}).get("delta"),
                "CE Gamma": ce.get("greeks", {}).get("gamma"),
                "CE Vega": ce.get("greeks", {}).get("vega"),

                # ---------- PUT ----------
                "PE LTP": pe.get("last_price"),
                "PE OI": pe.get("oi"),
                "PE Volume": pe.get("volume"),        # ✅ ADDED
                "PE IV": pe.get("implied_volatility"),
                "PE Delta": pe.get("greeks", {}).get("delta"),
                "PE Gamma": pe.get("greeks", {}).get("gamma"),
                "PE Vega": pe.get("greeks", {}).get("vega"),

                "timestamp": ts,
            })

        if not rows:
            continue

        df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

        # ================= FORCE NUMERIC =================
        num_cols = [
            "CE LTP","CE OI","CE Volume","CE IV","CE Delta","CE Gamma","CE Vega",
            "PE LTP","PE OI","PE Volume","PE IV","PE Delta","PE Gamma","PE Vega",
        ]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # ================= MAX PAIN =================
        df = compute_max_pain(df)

        # ================= COLUMN ORDER LOCK =================
        df = df[
            [
                "Strike",

                "CE LTP","CE OI","CE Volume","CE IV","CE Delta","CE Gamma","CE Vega",
                "PE LTP","PE OI","PE Volume","PE IV","PE Delta","PE Gamma","PE Vega",

                "timestamp",
                "Max Pain",
            ]
        ]

        out = f"{DATA_DIR}/{sym.lower()}.csv"
        df.to_csv(out, mode="a", header=not os.path.exists(out), index=False)

        print(f"[OK] {sym} saved @ {ts}")


if __name__ == "__main__":
    main()
