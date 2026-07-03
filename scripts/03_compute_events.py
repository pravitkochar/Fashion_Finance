"""Phase 3 — compute event-level returns / CARs / ARs.

For each show event, anchor t=0 at the first trading day on or after show_date for
that ticker, build a -30..+30 trading-day window, compute abnormal returns vs
the local benchmark and CAR sums.

Output: data/events.csv

Soft logs:
  - drop reasons appended to data/events_dropped.csv
  - weekend/holiday show_date shifted to next trading day (logged)
  - event window before listing date -> drop, log
  - <50 aligned trading days -> drop, log

Hard stop: any event computes to NaN/inf returns (after construction).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("phase3")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SHOWS = DATA / "show_dates.csv"
PRICES = DATA / "prices_raw.csv"
OUT = DATA / "events.csv"
DROPPED = DATA / "events_dropped.csv"

TICKER_BENCH = {
    "MC.PA": "^FCHI", "KER.PA": "^FCHI", "RMS.PA": "^FCHI",
    "CPRI": "^GSPC", "TPR": "^GSPC", "COH": "^GSPC", "PVH": "^GSPC", "RL": "^GSPC",
    "BRBY.L": "^FTSE",
    "1913.HK": "^HSI",
    "BC.MI": "FTSEMIB.MI", "MONC.MI": "FTSEMIB.MI",
    "SFER.MI": "FTSEMIB.MI", "TOD.MI": "FTSEMIB.MI",
    "BOSS.DE": "^GDAXI",
}

PRE = 30
POST = 30
MIN_DAYS_REQUIRED = 50


def main() -> int:
    if not SHOWS.exists():
        log.error("missing %s", SHOWS); sys.exit(2)
    if not PRICES.exists():
        log.error("missing %s", PRICES); sys.exit(2)

    shows = pd.read_csv(SHOWS, parse_dates=["show_date"])
    prices = pd.read_csv(PRICES, parse_dates=["date"])
    prices["date"] = prices["date"].dt.tz_localize(None).dt.normalize()
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)

    log.info("events in show_dates.csv: %d", len(shows))
    log.info("price tickers: %s", sorted(prices["ticker"].unique()))

    by_ticker: dict[str, pd.DataFrame] = {
        t: g.reset_index(drop=True) for t, g in prices.groupby("ticker")
    }

    rows = []
    drops = []

    for i, ev in shows.iterrows():
        eid = f"E{i:05d}"
        tk = ev["ticker"]
        bench = TICKER_BENCH.get(tk)
        if bench is None:
            drops.append([eid, tk, ev["brand_slug"], ev["season"], ev["year"], "no benchmark mapping"])
            continue
        if tk not in by_ticker:
            drops.append([eid, tk, ev["brand_slug"], ev["season"], ev["year"], "no ticker price data"])
            continue
        if bench not in by_ticker:
            drops.append([eid, tk, ev["brand_slug"], ev["season"], ev["year"], f"no benchmark price data ({bench})"])
            continue

        sdf = by_ticker[tk]
        bdf = by_ticker[bench][["date", "daily_return"]].rename(columns={"daily_return": "bench_ret"})

        td = sdf["date"].values
        sd = np.datetime64(ev["show_date"].to_datetime64())
        idx_arr = np.where(td >= sd)[0]
        if len(idx_arr) == 0:
            drops.append([eid, tk, ev["brand_slug"], ev["season"], ev["year"], "show_date after last trading day"])
            continue
        i0 = int(idx_arr[0])

        if i0 < PRE:
            drops.append([eid, tk, ev["brand_slug"], ev["season"], ev["year"],
                          f"pre-window before listing (i0={i0})"])
            continue
        if i0 + POST >= len(sdf):
            drops.append([eid, tk, ev["brand_slug"], ev["season"], ev["year"],
                          "post-window beyond available data"])
            continue

        t0_date = sdf.iloc[i0]["date"]
        win = sdf.iloc[i0 - PRE : i0 + POST + 1].copy()
        win["t"] = np.arange(-PRE, POST + 1)
        win = win.merge(bdf, on="date", how="left")

        if win["daily_return"].isna().any() or win["bench_ret"].isna().any():
            keep = win.dropna(subset=["daily_return", "bench_ret"])
            if len(keep) < MIN_DAYS_REQUIRED:
                drops.append([eid, tk, ev["brand_slug"], ev["season"], ev["year"],
                              f"only {len(keep)} aligned days"])
                continue
            win = win.dropna(subset=["daily_return", "bench_ret"]).reset_index(drop=True)
            win["t"] = np.where(win["t"].notna(), win["t"], np.nan)

        win["AR"] = win["daily_return"] - win["bench_ret"]
        win = win.sort_values("t").reset_index(drop=True)

        def car(lo: int, hi: int) -> float:
            sub = win[(win["t"] >= lo) & (win["t"] <= hi)]
            return float(sub["AR"].sum()) if len(sub) else float("nan")

        def ar_at(t: int) -> float:
            sub = win[win["t"] == t]
            return float(sub["AR"].iloc[0]) if len(sub) else float("nan")

        def cum_ret(series_col: str, lo: int, hi: int) -> float:
            sub = win[(win["t"] >= lo) & (win["t"] <= hi)]
            return float(sub[series_col].sum()) if len(sub) else float("nan")

        t0_iso = pd.to_datetime(t0_date).strftime("%Y-%m-%d")

        if t0_iso != ev["show_date"].strftime("%Y-%m-%d"):
            log.info("event %s: show=%s -> t0=%s (shifted)", eid, ev["show_date"].date(), t0_iso)

        rows.append({
            "event_id": eid,
            "brand_slug": ev["brand_slug"],
            "ticker": tk,
            "season": ev["season"],
            "year": int(ev["year"]),
            "show_date": ev["show_date"].strftime("%Y-%m-%d"),
            "designer": ev.get("designer", "") or "",
            "trading_day_t0": t0_iso,
            "local_index_used": bench,
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
            "raw_cum_return_t10":       cum_ret("daily_return", -30, 10),
            "benchmark_cum_return_t10": cum_ret("bench_ret",   -30, 10),
        })

    out = pd.DataFrame(rows)

    if out.empty:
        log.error("HARD STOP: 0 events computed"); sys.exit(2)

    numeric_cols = [c for c in out.columns if c.startswith(("CAR_", "AR_", "raw_", "benchmark_"))]
    bad_mask = out[numeric_cols].apply(lambda c: ~np.isfinite(c)).any(axis=1)
    n_bad = int(bad_mask.sum())
    if n_bad:
        bad_pct = n_bad / max(1, len(out))
        if bad_pct > 0.05:
            log.error("HARD STOP: %d/%d (%.1f%%) events with NaN/inf — exceeds 5%% data-gap budget",
                      n_bad, len(out), bad_pct * 100)
            out[bad_mask].to_csv(DATA / "events_bad.csv", index=False)
            sys.exit(2)
        log.warning("dropping %d/%d events with NaN/inf (data-gap)", n_bad, len(out))
        out[bad_mask].to_csv(DATA / "events_bad.csv", index=False)
        for _, r in out[bad_mask].iterrows():
            drops.append([r["event_id"], r["ticker"], r["brand_slug"], r["season"], r["year"],
                          "NaN/inf in computed return (data gap in window)"])
        out = out[~bad_mask].reset_index(drop=True)

    drop_df = pd.DataFrame(drops, columns=["event_id", "ticker", "brand_slug", "season", "year", "reason"])
    drop_df.to_csv(DROPPED, index=False)
    log.info("dropped %d events (see %s)", len(drop_df), DROPPED)

    out.to_csv(OUT, index=False)
    log.info("wrote %s rows=%d", OUT, len(out))
    log.info("Phase 3 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
