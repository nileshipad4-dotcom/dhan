import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# ---------------------------------
# PAGE
# ---------------------------------
st.set_page_config(layout="wide")
st.title("📊 NIFTY / BANKNIFTY Strike-wise Comparison")

# ---------------------------------
# CONFIG
# ---------------------------------
UNDERLYING = st.sidebar.selectbox("Index", ["NIFTY", "BANKNIFTY"])
CSV_PATH = f"data/{UNDERLYING.lower()}.csv"

FACTOR = 100_000_000

# ---------------------------------
# LOAD CSV
# ---------------------------------
df = pd.read_csv(CSV_PATH)

df["timestamp"] = df["timestamp"].astype(str).str[-5:]  # HH:MM
df["Strike"] = pd.to_numeric(df["Strike"], errors="coerce")
df["Max Pain"] = pd.to_numeric(df["Max Pain"], errors="coerce")

# ---------------------------------
# TIME SELECTION
# ---------------------------------
def rotated_time_sort(times, pivot="09:15"):
    pivot_min = int(pivot[:2]) * 60 + int(pivot[3:])
    def key(t):
        h, m = map(int, t.split(":"))
        return ((h * 60 + m) - pivot_min) % (24 * 60)
    return sorted(times, key=key, reverse=True)

timestamps = rotated_time_sort(df["timestamp"].unique())
t1 = st.selectbox("Time 1 (Latest)", timestamps, index=0)
t2 = st.selectbox("Time 2 (Previous)", timestamps, index=1)

# ---------------------------------
# HISTORICAL MAX PAIN
# ---------------------------------
mp_t1 = (
    df[df["timestamp"] == t1]
    .groupby("Strike", as_index=False)["Max Pain"]
    .sum()
    .rename(columns={"Max Pain": f"MP ({t1})"})
)

mp_t2 = (
    df[df["timestamp"] == t2]
    .groupby("Strike", as_index=False)["Max Pain"]
    .sum()
    .rename(columns={"Max Pain": f"MP ({t2})"})
)

merged = mp_t1.merge(mp_t2, on="Strike", how="outer")
merged["△ MP"] = merged[f"MP ({t1})"] - merged[f"MP ({t2})"]

# ---------------------------------
# GREEKS COMPARISON (T1 vs T2)
# ---------------------------------
def greek_delta(col):
    g1 = (
        df[df["timestamp"] == t1]
        .groupby("Strike")[col]
        .sum()
    )
    g2 = (
        df[df["timestamp"] == t2]
        .groupby("Strike")[col]
        .sum()
    )
    return (g1 - g2).rename(col + " △")

greeks = pd.concat(
    [
        greek_delta("CE Gamma"),
        greek_delta("PE Gamma"),
        greek_delta("CE Delta"),
        greek_delta("PE Delta"),
        greek_delta("CE Vega"),
        greek_delta("PE Vega"),
    ],
    axis=1,
).reset_index()

# ---------------------------------
# FINAL MERGE
# ---------------------------------
final = (
    merged
    .merge(greeks, on="Strike", how="left")
    .sort_values("Strike")
)

final = final.round(0)

# ---------------------------------
# DISPLAY
# ---------------------------------
st.subheader(f"{UNDERLYING} — {t1} vs {t2}")

st.dataframe(
    final,
    use_container_width=True,
    height=700
)

st.caption("MP = Max Pain | △ = Change between timestamps")
