

# collector.py
import requests
import pandas as pd
from datetime import datetime
import os

# ================= CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJwX2lwIjoiIiwic19pcCI6IiIsImlzcyI6ImRoYW4iLCJwYXJ0bmVySWQiOiIiLCJleHAiOjE3NjYzNDc3ODYsImlhdCI6MTc2NjI2MTM4NiwidG9rZW5Db25zdW1lclR5cGUiOiJTRUxGIiwid2ViaG9va1VybCI6Imh0dHBzOi8vbG9jYWxob3N0IiwiZGhhbkNsaWVudElkIjoiMTEwMjcxMjM4MCJ9.uQ4LyVOZqiy1ZyIENwcBT0Eei8taXbR8KgNW40NV0Y3nR_AQsmAC3JtZSoFE5p2xBwwB3q6ko_JEGTe7x_2ZTA"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {"scrip": 13, "seg": "IDX_I"},
    "BANKNIFTY": {"scrip": 25, "seg": "IDX_I"},
}

HEADERS = {
    "client-id": CLIENT_ID,
    "access-token": ACCESS_TOKEN,
    "Content-Type": "application/json",
}

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)


# ================= API FUNCTIONS =================
def get_expiries(scrip, seg):
    r = requests.post(
        f"{API_BASE}/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": scrip, "UnderlyingSeg": seg},
        timeout=10,
    )
    if r.status_code != 200:
        return []
    return r.json().get("data", [])


def get_option_chain(scrip, seg, expiry):
    r = requests.post(
        f"{API_BASE}/optionchain",
        headers=HEADERS,
        json={
            "UnderlyingScrip": scrip,
            "UnderlyingSeg": seg,
            "Expiry": expiry,
        },
        timeout=10,
    )
    if r.status_code != 200:
        return None
    return r.json().get("data")


# ================= MAX PAIN =================
def compute_max_pain(df):
    A = df["CE LTP"].fillna(0).values
    B = df["CE OI"].fillna(0).values
    G = df["Strike"].fillna(0).values
    L = df["PE OI"].fillna(0).values
    M = df["PE LTP"].fillna(0).values

    U = []
    for i in range(len(df)):
        Q = -sum(A[i:] * B[i:])
        R = G[i] * sum(B[:i]) - sum(G[:i] * B[:i])
        S = -sum(M[:i] * L[:i])
        T = sum(G[i:] * L[i:]) - G[i] * sum(L[i:])
        U.append(int((Q + R + S + T) / 10000))

    df["Max Pain"] = U
    return df


# ================= MAIN =================
def main():

    if not ACCESS_TOKEN:
        raise RuntimeError("DHAN_TOKEN is not set")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    for symbol, cfg in UNDERLYINGS.items():

        expiries = get_expiries(cfg["scrip"], cfg["seg"])
        if not expiries:
            print(f"[WARN] No expiries for {symbol}")
            continue

        expiry = expiries[0]
        data = get_option_chain(cfg["scrip"], cfg["seg"], expiry)
        if not data:
            print(f"[WARN] No option chain for {symbol}")
            continue

        oc = data.get("oc", {})
        rows = []

        for strike, v in oc.items():
            ce = v.get("ce", {})
            pe = v.get("pe", {})

            rows.append({
                "Strike": int(float(strike)),

                # ---------- CE ----------
                "CE LTP": ce.get("last_price"),
                "CE OI": ce.get("oi"),
                "CE Volume": ce.get("volume"),
                "CE IV": ce.get("implied_volatility"),
                "CE Delta": ce.get("greeks", {}).get("delta"),
                "CE Gamma": ce.get("greeks", {}).get("gamma"),
                "CE Vega": ce.get("greeks", {}).get("vega"),

                # ---------- PE ----------
                "PE LTP": pe.get("last_price"),
                "PE OI": pe.get("oi"),
                "PE Volume": pe.get("volume"),
                "PE IV": pe.get("implied_volatility"),
                "PE Delta": pe.get("greeks", {}).get("delta"),
                "PE Gamma": pe.get("greeks", {}).get("gamma"),
                "PE Vega": pe.get("greeks", {}).get("vega"),

                # ---------- META ----------
                "Expiry": expiry,
                "timestamp": timestamp,
            })

        if not rows:
            continue

        df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)

        # -------- MAX PAIN --------
        df = compute_max_pain(df)

        out_path = f"{DATA_DIR}/{symbol.lower()}.csv"

        df.to_csv(
            out_path,
            mode="a",
            header=not os.path.exists(out_path),
            index=False,
        )

        print(f"[OK] Saved {symbol} @ {timestamp}")


if __name__ == "__main__":
    main()

