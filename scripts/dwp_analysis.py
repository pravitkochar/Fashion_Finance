"""Off-spec ad-hoc — The Devil Wears Prada 1 (2006-06-30) + 2 (2026-05-01).

Reuses /data/prices_raw.csv via lib_event_study; fetches fresh 2026 data so
DWP2's pre-event window resolves. DWP2 has no post-release data yet (the film
opens within a few days of today), so we report pre-event CARs only for it.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib_event_study import TICKER_BENCH, COMPANY_NAME, ENTITY_TYPE, load_prices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dwp")

DATA = ROOT / "data"
OUT = DATA / "dwp_analysis.csv"

COMPANIES = [
    "MC.PA", "KER.PA", "CPRI", "TPR", "PVH",
    "RMS.PA", "BRBY.L", "1913.HK", "BC.MI", "MONC.MI",
    "BOSS.DE", "RL", "SFER.MI",
]
INDICES = list(set(TICKER_BENCH[t] for t in COMPANIES))

EVENTS = [
    ("DWP1", pd.Timestamp("2006-06-30")),
    ("DWP2", pd.Timestamp("2026-05-01")),
]

PRE = 30
POST = 30


def fetch_2026_prices() -> pd.DataFrame:
    frames = []
    for tk in COMPANIES + INDICES:
        df = yf.download(tk, start="2025-12-15", end="2026-05-15",
                         progress=False, auto_adjust=True, threads=False)
        if df is None or df.empty:
            log.warning("2026 fetch empty for %s", tk)
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        out = df[["Close"]].rename(columns={"Close": "adj_close"}).reset_index()
        out["ticker"] = tk
        out["date"] = pd.to_datetime(out["Date"]).dt.tz_localize(None).dt.normalize()
        frames.append(out[["date", "ticker", "adj_close"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def per_event_per_ticker(prices: pd.DataFrame, ticker: str, event_date: pd.Timestamp) -> dict:
    bench = TICKER_BENCH[ticker]
    by_t = {t: g.sort_values("date").reset_index(drop=True) for t, g in prices.groupby("ticker")}
    if ticker not in by_t or bench not in by_t:
        return {"ticker": ticker, "status": "no data"}
    sdf = by_t[ticker]
    bdf = by_t[bench][["date", "daily_return"]].rename(columns={"daily_return": "bench_ret"})
    td = sdf["date"].values
    sd = np.datetime64(event_date)
    idx = np.where(td >= sd)[0]
    if len(idx) == 0:
        return {"ticker": ticker, "status": "event after last trading day"}
    i0 = int(idx[0])
    if i0 < PRE:
        return {"ticker": ticker, "status": "pre-window before listing"}
    available_post = len(sdf) - 1 - i0
    win = sdf.iloc[i0 - PRE : min(i0 + POST + 1, len(sdf))].copy()
    win["t"] = np.arange(-PRE, -PRE + len(win))
    win = win.merge(bdf, on="date", how="left").dropna(subset=["daily_return", "bench_ret"])
    win["AR"] = win["daily_return"] - win["bench_ret"]

    def car(lo: int, hi: int) -> float | None:
        sub = win[(win["t"] >= lo) & (win["t"] <= hi)]
        if sub.empty or sub["t"].max() < hi:
            return None
        return float(sub["AR"].sum())

    def ar_at(t: int) -> float | None:
        sub = win[win["t"] == t]
        return float(sub["AR"].iloc[0]) if len(sub) else None

    return {
        "ticker": ticker,
        "company": COMPANY_NAME.get(ticker, ticker),
        "type": ENTITY_TYPE.get(ticker, ""),
        "benchmark": bench,
        "t0_date": pd.to_datetime(sdf.iloc[i0]["date"]).strftime("%Y-%m-%d"),
        "available_post_days": int(available_post),
        "CAR_pre30": car(-30, -1),
        "CAR_pre10": car(-10, -1),
        "CAR_pre5":  car(-5, -1),
        "CAR_0to1":  car(0, 1),
        "CAR_0to5":  car(0, 5),
        "CAR_0to10": car(0, 10),
        "CAR_0to30": car(0, 30),
        "AR_t1":     ar_at(1),
        "AR_t5":     ar_at(5),
        "AR_t10":    ar_at(10),
        "status":    "ok",
    }


def main() -> int:
    log.info("loading prices_raw.csv")
    base = load_prices(DATA / "prices_raw.csv")
    log.info("fetching fresh 2026 prices for %d tickers", len(COMPANIES) + len(INDICES))
    extra = fetch_2026_prices()
    base = base[["date", "ticker", "adj_close"]]
    if not extra.empty:
        combined = pd.concat([base, extra], ignore_index=True)
    else:
        combined = base.copy()
    combined = combined.drop_duplicates(["date", "ticker"]).sort_values(["ticker", "date"]).reset_index(drop=True)
    combined["daily_return"] = (combined.groupby("ticker", group_keys=False)["adj_close"]
                                .apply(lambda s: np.log(s / s.shift(1))))
    combined["date"] = pd.to_datetime(combined["date"]).dt.tz_localize(None).dt.normalize()
    log.info("combined: %d rows %s..%s", len(combined),
             combined["date"].min().date(), combined["date"].max().date())

    rows = []
    for label, ed in EVENTS:
        for tk in COMPANIES:
            r = per_event_per_ticker(combined, tk, ed)
            r["event"] = label
            r["event_date"] = ed.strftime("%Y-%m-%d")
            rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    for label, ed in EVENTS:
        sub = df[(df["event"] == label) & (df["status"] == "ok")].copy()
        if sub.empty:
            log.info("\n=== %s (%s) — no usable data ===", label, ed.date())
            continue
        log.info("\n=== %s (%s) — %d tickers with data ===", label, ed.date(), len(sub))
        cols = ["ticker", "company", "CAR_pre10", "CAR_pre5", "CAR_0to1",
                "CAR_0to5", "CAR_0to10", "AR_t1", "AR_t5"]
        sub = sub[cols].copy()
        for c in sub.columns:
            if c.startswith(("CAR_", "AR_")):
                sub[c] = sub[c].apply(lambda v: f"{v*100:+.2f}%" if pd.notna(v) else "—")
        log.info("\n" + sub.to_string(index=False))

    log.info("\nwrote %s", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
