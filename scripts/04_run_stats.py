"""Phase 4 + Phase 5 — confounders + the three statistical tests.

Phase 4: build data/confounders.csv flagging earnings_within_10d (and
confounder_unknown when yfinance returns no earnings data for a ticker).

Phase 5: run three tests on events joined with confounders. Output
data/phase1_findings.json. Generate reports/aggregate_CAR.png for Test 3 / chart.

Hard stop: NaN/non-finite test statistics.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("phase4_5")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
EVENTS = DATA / "events.csv"
PRICES = DATA / "prices_raw.csv"
SHOWS = DATA / "show_dates.csv"
CONFOUND = DATA / "confounders.csv"
FINDINGS = DATA / "phase1_findings.json"
AGG_CHART = REPORTS / "aggregate_CAR.png"

TICKER_BENCH = {
    "MC.PA": "^FCHI", "KER.PA": "^FCHI", "RMS.PA": "^FCHI",
    "CPRI": "^GSPC", "TPR": "^GSPC", "COH": "^GSPC", "PVH": "^GSPC", "RL": "^GSPC",
    "BRBY.L": "^FTSE",
    "1913.HK": "^HSI",
    "BC.MI": "FTSEMIB.MI", "MONC.MI": "FTSEMIB.MI",
    "SFER.MI": "FTSEMIB.MI", "TOD.MI": "FTSEMIB.MI",
    "BOSS.DE": "^GDAXI",
}

WINDOWS = [(-10, -1), (0, 1), (0, 5), (0, 10)]
WIN_NAMES = {(-10, -1): "CAR_pre10", (0, 1): "CAR_0to1", (0, 5): "CAR_0to5", (0, 10): "CAR_0to10"}

PRE = 30
POST = 30


def fetch_earnings_dates(ticker: str) -> set[pd.Timestamp]:
    try:
        tk = yf.Ticker(ticker)
        df = tk.earnings_dates
        if df is None or df.empty:
            return set()
        idx = pd.to_datetime(df.index).tz_localize(None).normalize()
        return set(idx)
    except Exception as e:
        log.warning("earnings fetch failed %s: %s", ticker, e)
        return set()


def build_confounders(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    rows = []
    earnings_by_ticker: dict[str, set] = {}
    unknown_tickers: set = set()

    for tk in sorted(events["ticker"].unique()):
        log.info("fetching earnings for %s", tk)
        s = fetch_earnings_dates(tk)
        if not s:
            unknown_tickers.add(tk)
            log.warning("%s: no earnings dates available", tk)
        earnings_by_ticker[tk] = s
        time.sleep(0.7)

    by_ticker_dates: dict[str, np.ndarray] = {
        t: np.sort(np.array(g["date"].dt.normalize().unique(), dtype="datetime64[ns]"))
        for t, g in prices.groupby("ticker")
    }

    for _, ev in events.iterrows():
        tk = ev["ticker"]
        eid = ev["event_id"]
        unknown = tk in unknown_tickers
        within = False

        if not unknown and tk in by_ticker_dates and earnings_by_ticker[tk]:
            td = by_ticker_dates[tk]
            t0 = np.datetime64(pd.to_datetime(ev["trading_day_t0"]))
            i0_arr = np.where(td >= t0)[0]
            if len(i0_arr):
                i0 = int(i0_arr[0])
                lo = max(0, i0 - 10)
                hi = min(len(td) - 1, i0 + 10)
                window_days = set(pd.to_datetime(td[lo:hi + 1]).normalize())
                within = any(d in window_days for d in earnings_by_ticker[tk])

        rows.append({
            "event_id": eid,
            "ticker": tk,
            "earnings_within_10d": bool(within),
            "confounder_unknown": bool(unknown),
            "confounded": bool(within),
        })

    return pd.DataFrame(rows)


def aggregate_car_curve(events: pd.DataFrame, prices: pd.DataFrame) -> pd.Series:
    """Mean AR per trading day t in [-PRE, +POST], then cumsum -> mean CAR curve."""
    ts = list(range(-PRE, POST + 1))
    sums = {t: 0.0 for t in ts}
    counts = {t: 0 for t in ts}

    by_ticker: dict[str, pd.DataFrame] = {
        t: g.sort_values("date").reset_index(drop=True) for t, g in prices.groupby("ticker")
    }

    for _, ev in events.iterrows():
        tk = ev["ticker"]
        bench = TICKER_BENCH.get(tk)
        if tk not in by_ticker or bench not in by_ticker:
            continue
        sdf = by_ticker[tk]
        bdf = by_ticker[bench][["date", "daily_return"]].rename(columns={"daily_return": "bench_ret"})
        td = sdf["date"].values
        sd = np.datetime64(pd.to_datetime(ev["show_date"]))
        idx_arr = np.where(td >= sd)[0]
        if len(idx_arr) == 0:
            continue
        i0 = int(idx_arr[0])
        if i0 < PRE or i0 + POST >= len(sdf):
            continue
        win = sdf.iloc[i0 - PRE : i0 + POST + 1].copy()
        win["t"] = np.arange(-PRE, POST + 1)
        win = win.merge(bdf, on="date", how="left").dropna(subset=["daily_return", "bench_ret"])
        win["AR"] = win["daily_return"] - win["bench_ret"]
        for _, r in win.iterrows():
            t = int(r["t"])
            sums[t] += float(r["AR"])
            counts[t] += 1

    mean_ar = pd.Series({t: (sums[t] / counts[t] if counts[t] else 0.0) for t in ts}).sort_index()
    return mean_ar.cumsum()


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)

    events = pd.read_csv(EVENTS)
    prices = pd.read_csv(PRICES, parse_dates=["date"])
    prices["date"] = prices["date"].dt.tz_localize(None).dt.normalize()
    log.info("events=%d prices=%d tickers=%d", len(events), len(prices), prices["ticker"].nunique())

    log.info("Phase 4: confounders ...")
    cf = build_confounders(events, prices)
    cf.to_csv(CONFOUND, index=False)
    log.info("wrote %s rows=%d (n_confounded=%d, n_unknown=%d)",
             CONFOUND, len(cf), int(cf["confounded"].sum()), int(cf["confounder_unknown"].sum()))

    df = events.merge(cf, on=["event_id", "ticker"], how="left")

    log.info("Phase 5 Test 1: aggregate t-stats ...")
    test1 = []
    for win in WINDOWS:
        col = WIN_NAMES[win]
        x = df[col].dropna().values
        if len(x) < 5:
            log.error("HARD STOP: <5 events for window %s", win); sys.exit(2)
        m = float(np.mean(x))
        sd = float(np.std(x, ddof=1))
        n = len(x)
        se = sd / np.sqrt(n) if sd > 0 else float("nan")
        t = m / se if se and np.isfinite(se) and se > 0 else float("nan")
        p = float(2 * (1 - stats.t.cdf(abs(t), df=n - 1))) if np.isfinite(t) else float("nan")
        if not (np.isfinite(t) and np.isfinite(p)):
            log.error("HARD STOP: NaN test stat for %s", col); sys.exit(2)
        flagged = bool(abs(t) > 1.96 or p < 0.05)
        test1.append({
            "window": col, "lo": win[0], "hi": win[1], "n": int(n),
            "mean_CAR": m, "sd": sd, "se": se, "t_stat": float(t),
            "p_value": float(p), "flagged": flagged,
        })
        log.info("  %s n=%d mean=%.4f t=%.3f p=%.4f flagged=%s", col, n, m, t, p, flagged)

    log.info("Phase 5 Test 2: median brand-level effects ...")
    by_co = df.groupby("ticker")["CAR_0to5"].median().rename("median_CAR_0to5").reset_index()
    by_co["n_events"] = df.groupby("ticker")["event_id"].count().values
    by_co["flagged"] = by_co["median_CAR_0to5"].abs() > 0.03
    test2 = {
        "company_results": by_co.to_dict(orient="records"),
        "n_flagged": int(by_co["flagged"].sum()),
        "flagged": bool(by_co["flagged"].any()),
    }
    log.info("  flagged companies (|median|>3%%): %d", test2["n_flagged"])

    log.info("Phase 5 Test 3: aggregate CAR curve peak deflection ...")
    curve = aggregate_car_curve(events, prices)
    peak = float(curve.abs().max())
    test3 = {"peak_deflection": peak, "flagged": bool(peak > 0.015)}
    log.info("  peak deflection=%.4f flagged=%s", peak, test3["flagged"])

    plt.figure(figsize=(10, 5))
    plt.plot(curve.index, curve.values, color="#222")
    plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("Aggregate mean CAR (-30..+30 trading days)")
    plt.xlabel("Trading day relative to show")
    plt.ylabel("Mean cumulative abnormal return")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(AGG_CHART, dpi=140)
    plt.close()
    log.info("  saved %s", AGG_CHART)

    findings = {
        "test1": test1,
        "test2": test2,
        "test3": test3,
        "any_flagged": bool(any(r["flagged"] for r in test1) or test2["flagged"] or test3["flagged"]),
        "n_events": int(len(df)),
        "n_companies": int(df["ticker"].nunique()),
    }
    FINDINGS.write_text(json.dumps(findings, indent=2))
    log.info("wrote %s", FINDINGS)
    log.info("Phase 4+5 complete. any_flagged=%s", findings["any_flagged"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
