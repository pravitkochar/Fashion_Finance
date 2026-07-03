"""P4 (V2) — fit cascade propagation on the TRAIN window only.

Three hops, all lag/coefficient estimates via lagged Pearson correlation +
OLS beta at the best (max signed r) lag, exactly as pre-registered:

  hop1  runway season share  -> retailer monthly mix     lags 0..12 months
  hop2  runway season share  -> Google Trends value_z    lags 0..12 months
  hop3  retailer mix z       -> supplier excess returns  lags 0..6 months
        (and commodity references, reported separately, never P&L)

Point-in-time: every series is assembled through known_date filtering at the
fit boundary. Pairs with < MIN_OBS overlapping months are excluded and
logged, never imputed (DECISIONS.md).

Outputs (data/):
  propagation_train.csv                fit on TRAIN 2017-01..2022-12
  propagation_fold{1,2,3}.csv          fit windows ending 2019-12/20-12/21-12
Columns: hop, retailer (or 'TRENDS'/ticker), material, lag_months,
         adoption_coef, r, n_obs, fit_end

Flags: --hops 1,2,3  --folds (also fit per-fold)  --train-only (default)
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import lib_trickle as lt

log = lt.get_logger("13_fit_propagation")

TRAIN_START, TRAIN_END = "2017-01-01", "2022-12-31"
FOLD_ENDS = ["2019-12-31", "2020-12-31", "2021-12-31"]
MIN_OBS = 12
LAGS_RUNWAY = range(0, 13)
LAGS_PAYOFF = range(0, 7)
PRICES_PATH = lt.PRICES / "prices_tier23.csv"


def monthly_runway(fit_end: str) -> pd.DataFrame:
    """Season-level runway shares as a monthly step function (ffill from
    known_date), one column per material, PIT-clamped at fit_end."""
    rmix = lt.read_csv_or_empty(lt.DATA / "runway_mix.csv")
    if rmix.empty:
        return pd.DataFrame()
    rmix = rmix[(rmix["level"] == "season")
                & rmix["material"].isin(lt.signal_materials())]
    rmix = lt.filter_known_asof(rmix, fit_end)
    if rmix.empty:
        return pd.DataFrame()
    rmix = rmix.copy()
    rmix["month"] = pd.to_datetime(rmix["known_date"]).dt.to_period("M")
    wide = (rmix.pivot_table(index="month", columns="material",
                             values="share", aggfunc="last"))
    idx = pd.period_range(wide.index.min(),
                          pd.Period(fit_end[:7], freq="M"), freq="M")
    return wide.reindex(idx).ffill()


def monthly_downstream(fit_end: str) -> pd.DataFrame:
    """(retailer, material) monthly shares, thin samples excluded,
    PIT-clamped. Wide: index month, columns (retailer, material)."""
    dmix = lt.read_csv_or_empty(lt.DATA / "downstream_mix.csv")
    if dmix.empty:
        return pd.DataFrame()
    dmix = dmix[~dmix["thin_sample"].astype(str).str.lower().eq("true")]
    dmix = dmix[dmix["material"].isin(lt.signal_materials())]
    dmix = lt.filter_known_asof(dmix, fit_end)
    if dmix.empty:
        return pd.DataFrame()
    dmix = dmix.copy()
    dmix["month"] = pd.PeriodIndex(dmix["month"], freq="M")
    return dmix.pivot_table(index="month", columns=["retailer", "material"],
                            values="share", aggfunc="mean")


def monthly_trends(fit_end: str) -> pd.DataFrame:
    """Per-material mean value_z, monthly. Wide: columns = material."""
    tr = lt.read_csv_or_empty(lt.TRENDS / "trends.csv")
    if tr.empty or "value_z" not in tr.columns:
        return pd.DataFrame()
    tr = tr[(tr["term_type"] == "material")
            & tr["material"].isin(lt.signal_materials())]
    tr = lt.filter_known_asof(tr, fit_end)
    tr = tr.dropna(subset=["value_z"]).copy()
    tr["month"] = pd.to_datetime(tr["date"]).dt.to_period("M")
    return tr.pivot_table(index="month", columns="material",
                          values="value_z", aggfunc="mean")


def monthly_supplier_excess(fit_end: str) -> pd.DataFrame:
    """Supplier monthly excess returns (vs bench where mapped, else vs
    supplier-basket mean) + commodity raw monthly returns."""
    if not PRICES_PATH.exists():
        return pd.DataFrame()
    px = pd.read_csv(PRICES_PATH, parse_dates=["date"])
    px = px[px["date"] <= fit_end]
    wide = (px.pivot_table(index="date", columns="ticker",
                           values="daily_return", aggfunc="last"))
    monthly = (1 + wide).resample("ME").prod() - 1
    monthly.index = monthly.index.to_period("M")
    uni = lt.load_universe()
    out = {}
    t3 = {s["ticker"]: s.get("bench") for s in uni["tier3_suppliers"]}
    basket = monthly[[t for t in t3 if t in monthly]].mean(axis=1)
    for ticker, bench in t3.items():
        if ticker not in monthly:
            continue
        ref = monthly[bench] if bench and bench in monthly else basket
        out[ticker] = monthly[ticker] - ref
    for c in uni["commodities"]:
        if c["ticker"] in monthly:
            out[c["ticker"]] = monthly[c["ticker"]]      # raw, reference only
    return pd.DataFrame(out)


def best_lag(x: pd.Series, y: pd.Series, lags) -> dict | None:
    """max-signed-r lag of x leading y; OLS beta of y on lagged x."""
    best = None
    for lag in lags:
        xl = x.shift(lag)
        pair = pd.concat([xl, y], axis=1, keys=["x", "y"]).dropna()
        if len(pair) < MIN_OBS or pair["x"].std() == 0 or pair["y"].std() == 0:
            continue
        r = float(np.corrcoef(pair["x"], pair["y"])[0, 1])
        if best is None or r > best["r"]:
            beta = r * pair["y"].std() / pair["x"].std()
            best = {"lag_months": lag, "r": round(r, 4),
                    "adoption_coef": round(float(beta), 4),
                    "n_obs": len(pair)}
    return best


def fit_window(fit_end: str, hops: set[int]) -> pd.DataFrame:
    rows, excluded = [], 0
    rw = monthly_runway(fit_end)

    if 1 in hops and not rw.empty:
        dm = monthly_downstream(fit_end)
        for col in (dm.columns if not dm.empty else []):
            retailer, material = col
            if material not in rw.columns:
                continue
            res = best_lag(rw[material], dm[col], LAGS_RUNWAY)
            if res is None:
                excluded += 1
                continue
            rows.append({"hop": 1, "entity": retailer,
                         "material": material, **res})

    if 2 in hops and not rw.empty:
        tz = monthly_trends(fit_end)
        for material in (tz.columns if not tz.empty else []):
            if material not in rw.columns:
                continue
            res = best_lag(rw[material], tz[material], LAGS_RUNWAY)
            if res is None:
                excluded += 1
                continue
            rows.append({"hop": 2, "entity": "TRENDS",
                         "material": material, **res})

    if 3 in hops:
        dm = monthly_downstream(fit_end)
        sup = monthly_supplier_excess(fit_end)
        if not dm.empty and not sup.empty:
            # cross-retailer mean mix z per material
            mat_mean = dm.T.groupby(level="material").mean().T
            mat_z = ((mat_mean - mat_mean.expanding(MIN_OBS).mean().shift(1))
                     / mat_mean.expanding(MIN_OBS).std(ddof=1).shift(1))
            mat2tick: dict[str, list[str]] = {}
            uni = lt.load_universe()
            for e in uni["tier3_suppliers"] + uni["commodities"]:
                for m in e.get("materials", []):
                    mat2tick.setdefault(m, []).append(e["ticker"])
            for material, tickers in mat2tick.items():
                if material not in mat_z.columns:
                    continue
                for ticker in tickers:
                    if ticker not in sup.columns:
                        continue
                    res = best_lag(mat_z[material], sup[ticker], LAGS_PAYOFF)
                    if res is None:
                        excluded += 1
                        continue
                    rows.append({"hop": 3, "entity": ticker,
                                 "material": material, **res})

    df = pd.DataFrame(rows)
    if not df.empty:
        df["fit_end"] = fit_end
    log.info("fit_end %s: %d estimates (%d pairs excluded < %d obs)",
             fit_end, len(df), excluded, MIN_OBS)
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hops", default="1,2,3")
    ap.add_argument("--folds", action="store_true",
                    help="also fit each CV fold window")
    args = ap.parse_args()
    hops = {int(h) for h in args.hops.split(",")}
    lt.ensure_dirs()

    train = fit_window(TRAIN_END, hops)
    if train.empty:
        log.warning("no estimates on TRAIN — upstream coverage still thin")
    else:
        train.to_csv(lt.DATA / "propagation_train.csv", index=False)
        log.info("propagation_train.csv: %d rows "
                 "(hop counts: %s)", len(train),
                 train["hop"].value_counts().to_dict())
    if args.folds:
        for k, fe in enumerate(FOLD_ENDS, start=1):
            fold = fit_window(fe, hops)
            if not fold.empty:
                fold.to_csv(lt.DATA / f"propagation_fold{k}.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
