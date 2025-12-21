# collector.py
import requests
import pandas as pd
from datetime import datetime
import os

# ================= CONFIG =================
CLIENT_ID = "1102712380"
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzY2NDQwMzk5LCJpYXQiOjE3NjYzNTM5OTksInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTAyNzEyMzgwIn0.pLY-IzrzCrJIYWLLxo5_FD10k4F1MkgFQB9BOyQm5kIf969v7q0nyxvfyl2NniyhrWDiVWWACAWrW8kxIf3cxA"

API_BASE = "https://api.dhan.co/v2"

UNDERLYINGS = {
    "NIFTY": {
        "scrip": 13,
        "seg": "IDX_I",
        "center": 26000,     # 👈 FIXED CENTER
    },
    "BANKNIFTY": {
        "scrip": 25,
        "seg": "IDX_I",
        "center": 60000,     # 👈 FIXED CENTER
    },
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

    from datetime import timezone, timedelta
    timestamp = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M")


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
        if not oc:
            continue

        # -------------------------------------------------
        # STRIKE FILTERING (25 BELOW + 25 ABOVE FIXED LEVEL)
        # -------------------------------------------------
        center = cfg["center"]

        strikes = sorted(float(s) for s in oc.keys())

        below = [s for s in strikes if s <= center][-25:]
        above = [s for s in strikes if s > center][:25]

        selected_strikes = set(below + above)

        # -------------------------------------------------
        # BUILD ROWS
        # -------------------------------------------------
        rows = []

        for strike in selected_strikes:
            v = oc.get(f"{strike:.6f}", {})
            ce = v.get("ce", {})
            pe = v.get("pe", {})

            rows.append({
                "Strike": int(strike),

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

        df = (
            pd.DataFrame(rows)
            .sort_values("Strike")
            .reset_index(drop=True)
        )

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
