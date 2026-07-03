"""P3 — estimate propagation lag and adoption coefficient per (retailer,
material) by cross-correlating the runway season vector against monthly
downstream mixes.

Method (locked in DECISIONS.md): the season-level runway share is placed at
its known_date month and forward-filled (a PIT-safe step function — at month
m the runway series holds the latest season known by m). For each lag in
0..12 months, Pearson r between the runway series shifted FORWARD by lag and
the retailer's downstream share. Best lag = argmax r (signed, not |r|).
adoption_coef = OLS beta of downstream on the lag-aligned runway series.
Pairs with < MIN_OBS overlapping months are excluded (NaN row, logged) — not
imputed.

Inputs:  data/runway_mix.csv (level=season), data/downstream_mix.csv
         (thin_sample rows excluded)
Outputs: data/propagation.csv, data/_propagation_grid.csv (full lag x r grid,
         dashboard diagnostics)
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import lib_trickle as lt

log = lt.get_logger("06_propagation_lag")

MAX_LAG = 12
MIN_OBS = 12


def _require(path, what: str) -> pd.DataFrame:
    df = lt.read_csv_or_empty(path)
    if df.empty:
        log.error("missing/empty upstream input: %s (%s)", path, what)
        sys.exit(1)
    return df


def runway_monthly(rmix: pd.DataFrame, months: pd.PeriodIndex) -> pd.DataFrame:
    """Wide monthly step-function frame: index=month period, cols=material."""
    season = rmix[rmix["level"] == "season"].copy()
    season["pm"] = pd.PeriodIndex(pd.to_datetime(season["known_date"]),
                                  freq="M")
    wide = season.pivot_table(index="pm", columns="material", values="share",
                              aggfunc="last")
    full = months.union(wide.index)
    return wide.reindex(full).ffill().reindex(months)


def best_lag(rw: pd.Series, ds: pd.Series) -> tuple[list[dict], dict]:
    """Grid rows + summary for one (retailer, material) pair."""
    grid, best = [], None
    for lag in range(MAX_LAG + 1):
        aligned = pd.concat([ds, rw.shift(lag)], axis=1, keys=["ds", "rw"]).dropna()
        n = len(aligned)
        r = np.nan
        if n >= MIN_OBS and aligned["ds"].std() > 0 and aligned["rw"].std() > 0:
            r = float(np.corrcoef(aligned["ds"], aligned["rw"])[0, 1])
        grid.append({"lag_months": lag, "r": r, "n_obs": n})
        if not np.isnan(r) and (best is None or r > best["r"]):
            var = float(aligned["rw"].var())
            beta = float(aligned["ds"].cov(aligned["rw"]) / var) if var > 0 else np.nan
            best = {"lag_months": lag, "r": r, "n_obs": n,
                    "adoption_coef": beta}
    if best is None:
        max_n = max(g["n_obs"] for g in grid)
        best = {"lag_months": np.nan, "r": np.nan, "n_obs": max_n,
                "adoption_coef": np.nan}
    return grid, best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()
    lt.ensure_dirs()

    rmix = _require(lt.DATA / "runway_mix.csv", "04_material_mix")
    dmix = _require(lt.DATA / "downstream_mix.csv", "04_material_mix")
    dmix = dmix[~dmix["thin_sample"].astype(str).str.lower().eq("true")]
    if dmix.empty:
        log.error("downstream_mix has no non-thin rows")
        return 1

    dmix = dmix.copy()
    dmix["pm"] = pd.PeriodIndex(dmix["month"], freq="M")
    months = pd.period_range(dmix["pm"].min(), dmix["pm"].max(), freq="M")
    rw_monthly = runway_monthly(rmix, months)

    mats = [m for m in lt.signal_materials() if m in rw_monthly.columns]
    retailers = sorted(dmix["retailer"].unique())
    log.info("grid: %d retailers x %d materials, %d months, lags 0..%d",
             len(retailers), len(mats), len(months), MAX_LAG)

    prop_rows, grid_rows, excluded = [], [], 0
    for retailer in retailers:
        sub = dmix[dmix["retailer"] == retailer]
        for mat in mats:
            ds = (sub[sub["material"] == mat].set_index("pm")["share"]
                  .reindex(months))
            grid, best = best_lag(rw_monthly[mat], ds)
            for g in grid:
                grid_rows.append({"retailer": retailer, "material": mat, **g})
            prop_rows.append({"retailer": retailer, "material": mat, **{
                k: best[k] for k in
                ("lag_months", "adoption_coef", "r", "n_obs")}})
            if np.isnan(best["r"]):
                excluded += 1
                log.info("excluded %s/%s: max overlap %d months "
                         "(need %d) or zero variance", retailer, mat,
                         best["n_obs"], MIN_OBS)

    n = lt.upsert_csv(pd.DataFrame(prop_rows), lt.DATA / "propagation.csv",
                      keys=["retailer", "material"],
                      sort_by=["retailer", "material"])
    ng = lt.upsert_csv(pd.DataFrame(grid_rows),
                       lt.DATA / "_propagation_grid.csv",
                       keys=["retailer", "material", "lag_months"],
                       sort_by=["retailer", "material", "lag_months"])
    est = len(prop_rows) - excluded
    log.info("propagation.csv: %d rows (%d estimated, %d excluded); "
             "grid: %d rows", n, est, excluded, ng)
    if est:
        got = pd.DataFrame(prop_rows).dropna(subset=["r"])
        log.info("median lag %.1f months, median r %.2f",
                 got["lag_months"].median(), got["r"].median())
    return 0


if __name__ == "__main__":
    sys.exit(main())
