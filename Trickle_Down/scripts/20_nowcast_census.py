"""Nowcast demo (pre-registered 2026-07-07 + depth expansion) — does the
cascade indicator lead official US clothing-store retail sales?

Judged on TURNING POINTS, not average error: for each local peak/trough in
the YoY growth of seasonally-adjusted clothing-store sales, did the
indicator's own turning point precede it at lead L? Precision AND recall,
leads 1-12, two indicators, against BOTH a persistence baseline (never
calls a turn: recall 0 by construction — reported, not hidden) and an AR(3)
fitted expanding on the sales series itself.

Indicators (both pseudo-real-time by construction — every input is used
only at its known_date):
  trends_composite    sum_m runway_share_m(t) * trends value_z_m(t), the
                      runway share forward-filled from season known_date
  measured_composite  same weighting over the 12m change in measured
                      cross-retailer mix share, expanding z (min 24 obs)

Sales: FRED, first available of MRTSSM448USS / RSCCAS (SA) for turning
points; MRTSSM448USN (NSA) kept for reference. Headline window <=2022-12;
2023+ computed but flagged eval_window=false. Ex-COVID robustness drops
turning points falling in 2020.

Outputs: reports/nowcast_census.csv, reports/findings_nowcast.json,
reports/img/nowcast_turning_points.png.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from scipy.signal import find_peaks

import lib_trickle as lt

log = lt.get_logger("20_nowcast")

DEV_END = "2022-12-31"
LEADS = range(1, 13)
TOL = 1                      # +/- months around t0 - L
SALES_PROM = 1.5             # percentage points of YoY, on 3m-smoothed
IND_PROM = 0.35              # z-units, on 3m-smoothed
AR_ORDER, AR_MIN_OBS = 3, 36


def fred_series(series_id: str) -> pd.Series | None:
    r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": series_id,
                             "api_key": os.environ["FRED_API_KEY"],
                             "file_type": "json",
                             "observation_start": "2014-01-01"},
                     timeout=30)
    if not r.ok:
        return None
    obs = [(o["date"], float(o["value"])) for o in r.json()["observations"]
           if o["value"] not in (".", "")]
    if not obs:
        return None
    s = pd.Series(dict(obs))
    s.index = pd.PeriodIndex(pd.to_datetime(s.index), freq="M")
    return s


# ---------------------------------------------------------- indicators ------

def runway_share_monthly() -> pd.DataFrame:
    rm = lt.read_csv_or_empty(lt.DATA / "runway_mix.csv")
    rm = rm[(rm["level"] == "season")
            & rm["material"].isin(lt.signal_materials())].copy()
    rm["month"] = pd.to_datetime(rm["known_date"]).dt.to_period("M")
    wide = rm.pivot_table(index="month", columns="material", values="share",
                          aggfunc="last")
    idx = pd.period_range(wide.index.min(), pd.Period("2026-07", "M"),
                          freq="M")
    return wide.reindex(idx).ffill()


def trends_z_monthly() -> pd.DataFrame:
    tr = lt.read_csv_or_empty(lt.TRENDS / "trends.csv")
    tr = tr[(tr["term_type"] == "material")
            & tr["material"].isin(lt.signal_materials())].dropna(
        subset=["value_z"]).copy()
    tr["month"] = pd.to_datetime(tr["date"]).dt.to_period("M")
    return tr.pivot_table(index="month", columns="material",
                          values="value_z", aggfunc="mean")


def measured_z_monthly() -> pd.DataFrame:
    dm = lt.read_csv_or_empty(lt.DATA / "downstream_mix.csv")
    dm = dm[~dm["thin_sample"].astype(str).str.lower().eq("true")]
    dm = dm[dm["material"].isin(lt.signal_materials())].copy()
    dm["month"] = pd.PeriodIndex(dm["month"], freq="M")
    share = dm.pivot_table(index="month", columns="material", values="share",
                           aggfunc="mean").sort_index()
    diff = share.diff(12)
    mu = diff.expanding(24).mean().shift(1)
    sd = diff.expanding(24).std(ddof=1).shift(1)
    return (diff - mu) / sd.replace(0, np.nan)


def composite(weights: pd.DataFrame, z: pd.DataFrame) -> pd.Series:
    idx = weights.index.intersection(z.index)
    out = {}
    for t in idx:
        w, v = weights.loc[t], z.loc[t]
        mats = [m for m in v.index
                if pd.notna(v[m]) and pd.notna(w.get(m, np.nan))]
        if len(mats) < 4:
            continue
        wv = w[mats].astype(float)
        out[t] = float((wv * v[mats].astype(float)).sum() / wv.sum())
    return pd.Series(out).sort_index()


# ------------------------------------------------------- turning points -----

def smooth(s: pd.Series) -> pd.Series:
    return s.rolling(3, center=True, min_periods=2).mean()


def turning_points(s: pd.Series, prominence: float) -> list[tuple]:
    sm = smooth(s).dropna()
    pk, _ = find_peaks(sm.values, prominence=prominence)
    tr, _ = find_peaks(-sm.values, prominence=prominence)
    return sorted([(sm.index[i], "peak") for i in pk]
                  + [(sm.index[i], "trough") for i in tr])


def score_lead(sales_tps: list, ind_tps: list, lead: int) -> dict:
    if not sales_tps:
        return {"precision": None, "recall": None, "n_sales_tps": 0,
                "n_ind_tps": len(ind_tps)}
    hits, used = 0, set()
    for t0, kind in sales_tps:
        target = t0 - lead
        for j, (ti, kj) in enumerate(ind_tps):
            if j in used or kj != kind:
                continue
            if abs((ti - target).n) <= TOL:
                hits += 1
                used.add(j)
                break
    recall = hits / len(sales_tps)
    precision = hits / len(ind_tps) if ind_tps else None
    return {"precision": None if precision is None else round(precision, 3),
            "recall": round(recall, 3), "hits": hits,
            "n_sales_tps": len(sales_tps), "n_ind_tps": len(ind_tps)}


def ar_forecast_series(y: pd.Series, lead: int) -> pd.Series:
    """Expanding AR(3), iterated `lead` steps ahead; forecast indexed at the
    month it targets (so its TPs are directly comparable to sales TPs)."""
    vals = y.dropna()
    out = {}
    for i in range(AR_MIN_OBS, len(vals) - 1):
        hist = vals.iloc[:i + 1].values
        X = np.column_stack([hist[k:len(hist) - AR_ORDER + k]
                             for k in range(AR_ORDER)] + [
            np.ones(len(hist) - AR_ORDER)])
        yv = hist[AR_ORDER:]
        try:
            beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
        except np.linalg.LinAlgError:
            continue
        window = list(hist[-AR_ORDER:])
        f = None
        for _ in range(lead):
            f = float(np.dot(beta[:AR_ORDER], window) + beta[AR_ORDER])
            window = window[1:] + [f]
        out[vals.index[i] + lead] = f
    return pd.Series(out).sort_index()


# ---------------------------------------------------------------- main ------

def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    lt.ensure_dirs()
    if not os.environ.get("FRED_API_KEY"):
        log.error("FRED_API_KEY missing")
        return 1

    sales_sa = None
    for sid in ("MRTSSM448USS", "RSCCAS"):
        sales_sa = fred_series(sid)
        if sales_sa is not None:
            log.info("SA sales series: %s (%d obs)", sid, len(sales_sa))
            break
    sales_nsa = fred_series("MRTSSM448USN")
    if sales_sa is None:
        log.error("no SA sales series available")
        return 1
    yoy = (sales_sa / sales_sa.shift(12) - 1) * 100

    weights = runway_share_monthly()
    ind = {"trends_composite": composite(weights, trends_z_monthly()),
           "measured_composite": composite(weights, measured_z_monthly())}
    for k, v in ind.items():
        log.info("indicator %s: %d months (%s..%s)", k, len(v),
                 v.index.min(), v.index.max())

    dev_cut = pd.Period(DEV_END[:7], "M")
    yoy_dev = yoy[yoy.index <= dev_cut]
    sales_tps = turning_points(yoy_dev, SALES_PROM)
    sales_tps_excov = [(t, k) for t, k in sales_tps if t.year != 2020]
    log.info("sales turning points (dev): %d (%d ex-COVID)",
             len(sales_tps), len(sales_tps_excov))

    findings = {"leads": {}, "corr_by_lead": {}, "ex_covid": {},
                "baselines": {}, "meta": {
                    "sales_tps": [(str(t), k) for t, k in sales_tps],
                    "dev_end": DEV_END, "tolerance_months": TOL,
                    "prominence": {"sales_pp": SALES_PROM, "ind_z": IND_PROM},
                    "pseudo_real_time": "all indicator inputs enter at their "
                                        "known_date; sales evaluated on the "
                                        "SA series as published"}}
    ind_tps = {k: turning_points(v[v.index <= dev_cut], IND_PROM)
               for k, v in ind.items()}
    for k, tps in ind_tps.items():
        log.info("indicator %s TPs (dev): %d", k, len(tps))

    header = f"{'lead':>4} | " + " | ".join(
        f"{k[:14]:>14}" for k in ind) + " |            ar3"
    log.info("turning-point recall/precision by lead:\n%s", header)
    for L in LEADS:
        row = {}
        for k, tps in ind_tps.items():
            row[k] = score_lead(sales_tps, tps, L)
        ar_tps = turning_points(ar_forecast_series(yoy_dev, L), SALES_PROM)
        row["ar3"] = score_lead(sales_tps, ar_tps, 0)
        findings["leads"][L] = row
        findings["ex_covid"][L] = {
            k: score_lead(sales_tps_excov,
                          [(t, kk) for t, kk in tps if t.year != 2020], L)
            for k, tps in ind_tps.items()}
        cors = {}
        for k, v in ind.items():
            pair = pd.concat([v.shift(0), yoy_dev], axis=1,
                             keys=["i", "y"]).dropna()
            pair["i"] = pair["i"].shift(0)
            merged = pd.concat([v.copy().rename("i").to_frame()["i"].shift(0),
                                yoy_dev.rename("y")], axis=1)
            merged["i_lag"] = merged["i"].shift(L)
            m = merged.dropna(subset=["i_lag", "y"])
            cors[k] = round(float(np.corrcoef(m["i_lag"], m["y"])[0, 1]), 3) \
                if len(m) >= 24 else None
        findings["corr_by_lead"][L] = cors
        log.info("%4d | %14s | %14s | %14s", L,
                 f"r{row['trends_composite']['recall']}/"
                 f"p{row['trends_composite']['precision']}",
                 f"r{row['measured_composite']['recall']}/"
                 f"p{row['measured_composite']['precision']}",
                 f"r{row['ar3']['recall']}/p{row['ar3']['precision']}")
    findings["baselines"]["persistence"] = {
        "recall": 0.0, "precision": None,
        "note": "persistence never calls a turn — recall 0 by construction; "
                "the honest bar is the AR(3) column."}

    # monthly export
    exp = pd.DataFrame({"sales_yoy_sa": yoy,
                        **{k: v for k, v in ind.items()}})
    exp["eval_window"] = exp.index <= dev_cut
    exp.index = exp.index.astype(str)
    exp.to_csv(lt.REPORTS / "nowcast_census.csv", index_label="month")
    with open(lt.REPORTS / "findings_nowcast.json", "w",
              encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)

    # chart
    fig, ax = plt.subplots(figsize=(11, 4.5))
    x = [p.to_timestamp() for p in yoy.index]
    ax.plot(x, yoy.values, color="#20242a", lw=1.3, label="sales YoY % (SA)")
    ax2 = ax.twinx()
    ti = ind["trends_composite"]
    ax2.plot([p.to_timestamp() for p in ti.index], ti.values,
             color="#3E6FB0", lw=1.1, alpha=0.8, label="cascade indicator")
    for t, kind in sales_tps:
        ax.axvline(t.to_timestamp(), color="#B6382E", alpha=0.35,
                   ls="--" if kind == "trough" else "-")
    ax.axvline(pd.Timestamp("2023-01-01"), color="#888", lw=0.8)
    ax.set_title("Clothing-store sales YoY vs cascade indicator "
                 "(red = turning points; right of grey line = out of dev)")
    ax.legend(loc="upper left")
    ax2.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(lt.REPORTS / "img" / "nowcast_turning_points.png", dpi=120)
    plt.close(fig)
    best = max(((L, r["trends_composite"]["recall"]) for L, r in
                findings["leads"].items()
                if r["trends_composite"]["recall"] is not None),
               key=lambda t: t[1], default=(None, None))
    log.info("VERDICT nowcast: best trends-composite recall %s at lead %s; "
             "see findings_nowcast.json for the full grid", best[1], best[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
