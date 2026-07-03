"""Shared event-study primitives.

Reused by every brief in this repo. Keeps the per-brief scripts focused on
event-source scraping and reporting; the math lives here.

Public API:
    TICKER_BENCH, ENTITY_TYPE, COMPANY_NAME    universe metadata
    load_prices(path)                          parse prices_raw.csv -> DataFrame
    build_event_window(events, prices)         dict[event_id] -> per-day AR window
    compute_event_metrics(events, prices)      one row per event with CARs / ARs
    aggregate_car_curve(events, prices)        Series (t -> mean cumulative AR)
    run_test1(events_df)                       aggregate t-stats across 4 windows
    run_test2(events_df)                       per-ticker median CAR_0to5 with 3% flag
    run_test3(curve)                           peak abs deflection with 1.5% flag
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

PRE = 30
POST = 30
MIN_DAYS_REQUIRED = 50

TICKER_BENCH = {
    "MC.PA": "^FCHI", "KER.PA": "^FCHI", "RMS.PA": "^FCHI",
    "CPRI": "^GSPC", "TPR": "^GSPC", "COH": "^GSPC", "PVH": "^GSPC", "RL": "^GSPC",
    "BRBY.L": "^FTSE",
    "1913.HK": "^HSI",
    "BC.MI": "FTSEMIB.MI", "MONC.MI": "FTSEMIB.MI",
    "SFER.MI": "FTSEMIB.MI", "TOD.MI": "FTSEMIB.MI",
    "BOSS.DE": "^GDAXI",
}

ENTITY_TYPE = {
    "MC.PA": "Conglomerate", "KER.PA": "Conglomerate", "CPRI": "Conglomerate",
    "TPR": "Conglomerate", "COH": "Conglomerate", "PVH": "Conglomerate",
    "RMS.PA": "Pure-play", "BRBY.L": "Pure-play", "1913.HK": "Pure-play",
    "BC.MI": "Pure-play", "MONC.MI": "Pure-play", "BOSS.DE": "Pure-play",
    "RL": "Pure-play", "SFER.MI": "Pure-play", "TOD.MI": "Pure-play",
}

COMPANY_NAME = {
    "MC.PA": "LVMH", "KER.PA": "Kering", "CPRI": "Capri Holdings",
    "TPR": "Tapestry", "COH": "Coach Inc (legacy)", "PVH": "PVH Corp",
    "RMS.PA": "Hermes", "BRBY.L": "Burberry", "1913.HK": "Prada",
    "BC.MI": "Brunello Cucinelli", "MONC.MI": "Moncler", "BOSS.DE": "Hugo Boss",
    "RL": "Ralph Lauren", "SFER.MI": "Salvatore Ferragamo", "TOD.MI": "Tod's",
}

WINDOWS_T1 = [(-10, -1), (0, 1), (0, 5), (0, 10)]
WIN_NAMES = {(-10, -1): "CAR_pre10", (0, 1): "CAR_0to1", (0, 5): "CAR_0to5", (0, 10): "CAR_0to10"}


def load_prices(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = df["date"].dt.tz_localize(None).dt.normalize()
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def _by_ticker(prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {t: g.reset_index(drop=True) for t, g in prices.groupby("ticker")}


def build_event_window(events: pd.DataFrame, prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return event_id -> per-day [t, AR, date] DataFrame for events that fit.

    `events` must have columns: event_id, ticker, show_date (datetime).
    """
    by_t = _by_ticker(prices)
    out: dict[str, pd.DataFrame] = {}
    for _, ev in events.iterrows():
        tk = ev["ticker"]
        bench = TICKER_BENCH.get(tk)
        if tk not in by_t or bench not in by_t:
            continue
        sdf = by_t[tk]
        bdf = by_t[bench][["date", "daily_return"]].rename(columns={"daily_return": "bench_ret"})
        td = sdf["date"].values
        sd = np.datetime64(pd.to_datetime(ev["show_date"]))
        idx = np.where(td >= sd)[0]
        if len(idx) == 0:
            continue
        i0 = int(idx[0])
        if i0 < PRE or i0 + POST >= len(sdf):
            continue
        win = sdf.iloc[i0 - PRE : i0 + POST + 1].copy()
        win["t"] = np.arange(-PRE, POST + 1)
        win = win.merge(bdf, on="date", how="left").dropna(subset=["daily_return", "bench_ret"])
        if len(win) < MIN_DAYS_REQUIRED:
            continue
        win["AR"] = win["daily_return"] - win["bench_ret"]
        out[ev["event_id"]] = win[["t", "AR", "date"]].reset_index(drop=True)
    return out


def compute_event_metrics(events: pd.DataFrame, prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (events_with_metrics, drops_log).

    `events` must have: event_id, ticker, show_date and any other cols you want to keep.
    """
    by_t = _by_ticker(prices)
    rows, drops = [], []
    for _, ev in events.iterrows():
        eid = ev["event_id"]; tk = ev["ticker"]
        bench = TICKER_BENCH.get(tk)
        if bench is None:
            drops.append([eid, tk, "no benchmark mapping"]); continue
        if tk not in by_t:
            drops.append([eid, tk, "no ticker price data"]); continue
        if bench not in by_t:
            drops.append([eid, tk, f"no benchmark price data ({bench})"]); continue

        sdf = by_t[tk]
        bdf = by_t[bench][["date", "daily_return"]].rename(columns={"daily_return": "bench_ret"})
        td = sdf["date"].values
        sd = np.datetime64(pd.to_datetime(ev["show_date"]))
        idx_arr = np.where(td >= sd)[0]
        if len(idx_arr) == 0:
            drops.append([eid, tk, "show_date after last trading day"]); continue
        i0 = int(idx_arr[0])
        if i0 < PRE:
            drops.append([eid, tk, f"pre-window before listing (i0={i0})"]); continue
        if i0 + POST >= len(sdf):
            drops.append([eid, tk, "post-window beyond available data"]); continue

        t0_date = sdf.iloc[i0]["date"]
        win = sdf.iloc[i0 - PRE : i0 + POST + 1].copy()
        win["t"] = np.arange(-PRE, POST + 1)
        win = win.merge(bdf, on="date", how="left")

        if win["daily_return"].isna().any() or win["bench_ret"].isna().any():
            keep = win.dropna(subset=["daily_return", "bench_ret"])
            if len(keep) < MIN_DAYS_REQUIRED:
                drops.append([eid, tk, f"only {len(keep)} aligned days"]); continue
            win = keep.reset_index(drop=True)

        win["AR"] = win["daily_return"] - win["bench_ret"]
        win = win.sort_values("t").reset_index(drop=True)

        def car(lo: int, hi: int) -> float:
            sub = win[(win["t"] >= lo) & (win["t"] <= hi)]
            return float(sub["AR"].sum()) if len(sub) else float("nan")

        def ar_at(t: int) -> float:
            sub = win[win["t"] == t]
            return float(sub["AR"].iloc[0]) if len(sub) else float("nan")

        def cum_ret(col: str, lo: int, hi: int) -> float:
            sub = win[(win["t"] >= lo) & (win["t"] <= hi)]
            return float(sub[col].sum()) if len(sub) else float("nan")

        row = {k: ev[k] for k in ev.index}
        row.update({
            "trading_day_t0": pd.to_datetime(t0_date).strftime("%Y-%m-%d"),
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
            "benchmark_cum_return_t10": cum_ret("bench_ret", -30, 10),
        })
        rows.append(row)

    out = pd.DataFrame(rows)
    drop_df = pd.DataFrame(drops, columns=["event_id", "ticker", "reason"])
    return out, drop_df


def aggregate_car_curve(events: pd.DataFrame, prices: pd.DataFrame) -> pd.Series:
    """Mean AR per t in [-PRE, +POST], cumulative-summed -> mean CAR curve."""
    ts = list(range(-PRE, POST + 1))
    sums = {t: 0.0 for t in ts}; counts = {t: 0 for t in ts}
    by_t = _by_ticker(prices)
    for _, ev in events.iterrows():
        tk = ev["ticker"]; bench = TICKER_BENCH.get(tk)
        if tk not in by_t or bench not in by_t:
            continue
        sdf = by_t[tk]
        bdf = by_t[bench][["date", "daily_return"]].rename(columns={"daily_return": "bench_ret"})
        td = sdf["date"].values
        sd = np.datetime64(pd.to_datetime(ev["show_date"]))
        idx = np.where(td >= sd)[0]
        if len(idx) == 0:
            continue
        i0 = int(idx[0])
        if i0 < PRE or i0 + POST >= len(sdf):
            continue
        win = sdf.iloc[i0 - PRE : i0 + POST + 1].copy()
        win["t"] = np.arange(-PRE, POST + 1)
        win = win.merge(bdf, on="date", how="left").dropna(subset=["daily_return", "bench_ret"])
        win["AR"] = win["daily_return"] - win["bench_ret"]
        for _, r in win.iterrows():
            t = int(r["t"]); sums[t] += float(r["AR"]); counts[t] += 1
    mean_ar = pd.Series({t: (sums[t] / counts[t] if counts[t] else 0.0) for t in ts}).sort_index()
    return mean_ar.cumsum()


def run_test1(df: pd.DataFrame) -> list[dict]:
    """Aggregate t-stat across the 4 standard windows. Returns list of dicts."""
    results = []
    for win in WINDOWS_T1:
        col = WIN_NAMES[win]
        x = df[col].dropna().values
        if len(x) < 5:
            results.append({"window": col, "n": int(len(x)), "mean_CAR": float("nan"),
                            "t_stat": float("nan"), "p_value": float("nan"), "flagged": False,
                            "error": "<5 events"})
            continue
        m = float(np.mean(x)); sd = float(np.std(x, ddof=1)); n = len(x)
        se = sd / np.sqrt(n) if sd > 0 else float("nan")
        t = m / se if se and np.isfinite(se) and se > 0 else float("nan")
        p = float(2 * (1 - stats.t.cdf(abs(t), df=n - 1))) if np.isfinite(t) else float("nan")
        results.append({"window": col, "lo": win[0], "hi": win[1], "n": int(n),
                        "mean_CAR": m, "sd": sd, "se": se, "t_stat": float(t),
                        "p_value": float(p),
                        "flagged": bool(np.isfinite(t) and (abs(t) > 1.96 or p < 0.05))})
    return results


def run_test2(df: pd.DataFrame, group_col: str = "ticker", threshold: float = 0.03) -> dict:
    """Per-group median CAR_0to5; flag any |median| > threshold."""
    by = df.groupby(group_col)["CAR_0to5"].median().rename("median_CAR_0to5").reset_index()
    by["n_events"] = df.groupby(group_col)["event_id"].count().values
    by["flagged"] = by["median_CAR_0to5"].abs() > threshold
    return {"company_results": by.to_dict(orient="records"),
            "n_flagged": int(by["flagged"].sum()),
            "flagged": bool(by["flagged"].any()),
            "threshold": threshold,
            "group_col": group_col}


def run_test3(curve: pd.Series, threshold: float = 0.015) -> dict:
    peak = float(curve.abs().max())
    return {"peak_deflection": peak, "flagged": bool(peak > threshold), "threshold": threshold}
