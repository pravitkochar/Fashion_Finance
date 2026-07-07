"""H5 — cascade indicators vs commodity futures (DECISIONS.md 2026-07-07).

Implements the H5 pre-registration EXACTLY:
  cells = indicator {search value_z composite, runway share z}
          x group {leather->LE=F, cotton+denim->CT=F, polyester+nylon->CL=F}
          x forward horizon {3,6,9} months (raw futures returns)
  per cell: Pearson r; Newey-West t (Bartlett weights, lag = horizon);
            circular moving-block bootstrap two-sided p (2,000 draws, block
            length = horizon, indicator resampled under H0); sign-agreement;
            n. Dev window 2017-01..2022-12; 2023+ computed, eval_window=false.
  headline cell (declared): leather / search / 6m.
  tradability: walk-forward folds validating 2020/2021/2022 — monthly
            |z|>1-gated position, direction = sign of fit-window correlation
            (in-sample only), net 10 bps/side on position changes; fold IRs.
  secondary: house emergence vs parent fwd {3,6}m excess, pooled Spearman,
            season-clustered bootstrap p (2,000 draws).

Outputs: reports/findings_h5.json, reports/h5_cells.csv,
         reports/img/h5_leather_search.png. Verdicts in the log.
"""
from __future__ import annotations

import json
import sys
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

import lib_trickle as lt

log = lt.get_logger("22_h5")

DEV_START, DEV_END = "2017-01", "2022-12"
HORIZONS = (3, 6, 9)
GROUPS = {"LE=F": ["leather"], "CT=F": ["cotton", "denim"],
          "CL=F": ["polyester", "nylon"]}
FOLD_YEARS = (2020, 2021, 2022)
COST_BPS = 10.0
N_BOOT = 2000
RNG = np.random.default_rng(7)


# ---------------------------------------------------------------- data ------

def monthly_returns(path, tickers=None) -> pd.DataFrame:
    px = pd.read_csv(path, parse_dates=["date"])
    if tickers:
        px = px[px["ticker"].isin(tickers)]
    wide = px.pivot_table(index="date", columns="ticker",
                          values="daily_return", aggfunc="last")
    m = (1 + wide.fillna(0)).resample("ME").prod() - 1
    m[wide.resample("ME").count() == 0] = np.nan
    m.index = m.index.to_period("M")
    return m


def fwd_return(monthly: pd.Series, k: int) -> pd.Series:
    cum = (1 + monthly.fillna(0)).cumprod()
    fwd = cum.shift(-k) / cum - 1
    fwd[monthly.isna()] = np.nan
    return fwd


def search_composite() -> pd.DataFrame:
    tr = lt.read_csv_or_empty(lt.TRENDS / "trends.csv")
    tr = tr[tr["term_type"] == "material"].dropna(subset=["value_z"]).copy()
    tr["month"] = pd.to_datetime(tr["date"]).dt.to_period("M")
    tz = tr.pivot_table(index="month", columns="material", values="value_z",
                        aggfunc="mean")
    return pd.DataFrame({c: tz[[m for m in mats if m in tz.columns]].mean(axis=1)
                         for c, mats in GROUPS.items()})


def runway_z() -> pd.DataFrame:
    rm = lt.read_csv_or_empty(lt.DATA / "runway_mix.csv")
    s = rm[(rm["level"] == "season")
           & rm["material"].isin(lt.signal_materials())].copy()
    s["month"] = pd.to_datetime(s["known_date"]).dt.to_period("M")
    wide = (s.pivot_table(index="month", columns="material", values="share",
                          aggfunc="last")
            .reindex(pd.period_range("2015-01", "2026-12", freq="M")).ffill())
    z = (wide - wide.shift(1).rolling(36, min_periods=12).mean()) / \
        wide.shift(1).rolling(36, min_periods=12).std(ddof=1).replace(0, np.nan)
    return pd.DataFrame({c: z[[m for m in mats if m in z.columns]].mean(axis=1)
                         for c, mats in GROUPS.items()})


# ----------------------------------------------------------- inference ------

def newey_west_t(x: np.ndarray, y: np.ndarray, lag: int) -> float:
    """HAC t-stat of the slope in y = a + b x (Bartlett weights)."""
    X = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ beta
    n, k = X.shape
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        G = Xe[l:].T @ Xe[:-l]
        S += w * (G + G.T)
    XtX_inv = np.linalg.inv(X.T @ X)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(max(cov[1, 1], 1e-12))
    return float(beta[1] / se)


def block_bootstrap_p(x: np.ndarray, y: np.ndarray, block: int,
                      n_boot: int = N_BOOT) -> float:
    """Two-sided p for corr(x,y): circular moving-block resample of x
    (breaks the association, preserves x's autocorrelation)."""
    n = len(x)
    r_obs = abs(np.corrcoef(x, y)[0, 1])
    n_blocks = int(np.ceil(n / block))
    hits = 0
    for _ in range(n_boot):
        starts = RNG.integers(0, n, size=n_blocks)
        idx = np.concatenate([(s + np.arange(block)) % n for s in starts])[:n]
        r_b = abs(np.corrcoef(x[idx], y)[0, 1])
        if r_b >= r_obs:
            hits += 1
    return round((hits + 1) / (n_boot + 1), 4)


# --------------------------------------------------------------- cells ------

def run_cells(indicators: dict, mcom: pd.DataFrame) -> list[dict]:
    dev = pd.period_range(DEV_START, DEV_END, freq="M")
    rows = []
    for iname, panel in indicators.items():
        for com in GROUPS:
            if com not in mcom.columns or com not in panel.columns:
                continue
            for k in HORIZONS:
                fwd = fwd_return(mcom[com], k)
                pair_all = pd.concat([panel[com], fwd], axis=1,
                                     keys=["ind", "fwd"]).dropna()
                for window, tag in [(pair_all[pair_all.index.isin(dev)], True),
                                    (pair_all[pair_all.index > dev[-1]], False)]:
                    if len(window) < 12:
                        if tag:
                            rows.append({"indicator": iname, "commodity": com,
                                         "horizon_m": k, "eval_window": tag,
                                         "n": len(window)})
                        continue
                    x = window["ind"].to_numpy()
                    y = window["fwd"].to_numpy()
                    r = float(np.corrcoef(x, y)[0, 1])
                    rows.append({
                        "indicator": iname, "commodity": com, "horizon_m": k,
                        "eval_window": tag, "n": len(window),
                        "pearson_r": round(r, 3),
                        "nw_t": round(newey_west_t(x, y, lag=k), 2),
                        "block_boot_p": block_bootstrap_p(x, y, block=k),
                        "sign_agree": round(float(((x > 0) == (y > 0)).mean()), 3),
                    })
    return rows


# --------------------------------------------------------------- folds ------

def run_folds(indicators: dict, mcom: pd.DataFrame) -> dict:
    out: dict = {}
    for iname, panel in indicators.items():
        for com in GROUPS:
            if com not in mcom.columns or com not in panel.columns:
                continue
            fold_irs = {}
            for year in FOLD_YEARS:
                fit_end = pd.Period(f"{year - 1}-12", freq="M")
                fit = pd.concat([panel[com], fwd_return(mcom[com], 6)], axis=1,
                                keys=["ind", "fwd"]).dropna()
                fit = fit[(fit.index >= DEV_START) & (fit.index <= fit_end)]
                if len(fit) < 12:
                    fold_irs[str(year)] = None
                    continue
                direction = np.sign(np.corrcoef(fit["ind"], fit["fwd"])[0, 1])
                val = pd.period_range(f"{year}-01", f"{year}-12", freq="M")
                z = panel[com].reindex(val)
                pos = pd.Series(np.where(z.abs() > 1, direction * np.sign(z), 0.0),
                                index=val)
                ret = mcom[com].reindex(val).shift(-1)   # position earns next month
                strat = (pos * ret).dropna()
                costs = pos.diff().abs().fillna(pos.abs()) * COST_BPS / 1e4
                strat = strat - costs.reindex(strat.index).fillna(0)
                if strat.std(ddof=1) == 0 or len(strat) < 6:
                    fold_irs[str(year)] = None
                    continue
                fold_irs[str(year)] = round(float(strat.mean() / strat.std(ddof=1)
                                                  * np.sqrt(12)), 3)
            vals = [v for v in fold_irs.values() if v is not None]
            out[f"{iname}|{com}"] = {"folds": fold_irs,
                                     "mean_ir": round(float(np.mean(vals)), 3)
                                     if vals else None}
    return out


# ----------------------------------------------------------- secondary ------

def parent_emergence() -> dict:
    rm = lt.read_csv_or_empty(lt.DATA / "runway_mix.csv")
    b = rm[(rm["level"] == "brand")
           & rm["material"].isin(lt.signal_materials())].copy()
    piv = b.pivot_table(index=["key", "season_code"], columns="material",
                        values="share", aggfunc="last")
    uni = lt.load_universe()
    parent = {h["slug"]: h["parent_ticker"] for h in uni["tier1_runway"]
              if h["parent_ticker"]}
    sys.path.insert(0, str(lt.PARENT_ROOT / "scripts"))
    import lib_event_study as les
    mpar = monthly_returns(lt.PARENT_PRICES)
    obs = []
    for brand in piv.index.get_level_values(0).unique():
        tick = parent.get(brand)
        if not tick or tick not in mpar.columns:
            continue
        sub = piv.loc[brand]
        sub = sub.loc[sorted(sub.index, key=lt.season_sort_key)]
        delta = sub - sub.shift(1).rolling(3, min_periods=3).mean()
        emerg = delta.clip(lower=0).sum(axis=1).dropna()
        bench = les.TICKER_BENCH.get(tick)
        for season, e in emerg.items():
            kd = lt.season_known_date(season)
            if not (date(2017, 1, 1) <= kd <= date(2022, 12, 31)):
                continue
            m = pd.Period(kd, freq="M")
            for k in (3, 6):
                fv = fwd_return(mpar[tick], k).get(m, np.nan)
                fb = (fwd_return(mpar[bench], k).get(m, np.nan)
                      if bench in mpar.columns else np.nan)
                if np.isfinite(fv) and np.isfinite(fb):
                    obs.append({"season": season, "k": k,
                                "emerg": float(e), "ex": float(fv - fb)})
    df = pd.DataFrame(obs)
    res = {}
    for k in (3, 6):
        sub = df[df["k"] == k]
        if len(sub) < 12:
            res[f"fwd{k}m"] = {"n": len(sub)}
            continue
        rho = float(stats.spearmanr(sub["emerg"], sub["ex"]).statistic)
        seasons = sub["season"].unique()
        hits = 0
        for _ in range(N_BOOT):
            pick = RNG.choice(seasons, size=len(seasons), replace=True)
            bs = pd.concat([sub[sub["season"] == s] for s in pick])
            r_b = stats.spearmanr(bs["emerg"], bs["ex"]).statistic
            if np.isfinite(r_b) and abs(r_b) >= abs(rho):
                hits += 1
        res[f"fwd{k}m"] = {"spearman": round(rho, 3),
                           "cluster_boot_p": round((hits + 1) / (N_BOOT + 1), 4),
                           "n": len(sub), "n_seasons": len(seasons)}
    return res


# ---------------------------------------------------------------- main ------

def chart(indicators: dict, mcom: pd.DataFrame) -> None:
    ind = indicators["search"]["LE=F"]
    fwd = fwd_return(mcom["LE=F"], 6)
    pair = pd.concat([ind, fwd], axis=1, keys=["z", "fwd"]).dropna()
    pair = pair[(pair.index >= DEV_START) & (pair.index <= DEV_END)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
    t = pair.index.to_timestamp()
    a1.plot(t, pair["z"], lw=1.3, label="leather search z")
    a1b = a1.twinx()
    a1b.plot(t, pair["fwd"], lw=1.1, color="tab:red", alpha=.7,
             label="LE=F fwd 6m")
    a1.set_title("Headline cell: leather search z vs LE=F fwd 6m (dev)")
    a1.legend(loc="upper left"); a1b.legend(loc="upper right")
    a2.scatter(pair["z"], pair["fwd"], s=14, alpha=.6)
    a2.axhline(0, lw=.5, color="grey"); a2.axvline(0, lw=.5, color="grey")
    a2.set_xlabel("indicator z"); a2.set_ylabel("fwd 6m return")
    r = np.corrcoef(pair["z"], pair["fwd"])[0, 1]
    a2.set_title(f"r = {r:.2f}, n = {len(pair)}")
    fig.tight_layout()
    fig.savefig(lt.REPORTS / "img" / "h5_leather_search.png", dpi=120)
    plt.close(fig)


def main() -> int:
    lt.ensure_dirs()
    mcom = monthly_returns(lt.PRICES / "prices_tier23.csv", list(GROUPS))
    indicators = {"search": search_composite(), "runway": runway_z()}
    cells = run_cells(indicators, mcom)
    folds = run_folds(indicators, mcom)
    secondary = parent_emergence()
    pd.DataFrame(cells).to_csv(lt.REPORTS / "h5_cells.csv", index=False)
    headline = next((c for c in cells
                     if c["indicator"] == "search" and c["commodity"] == "LE=F"
                     and c["horizon_m"] == 6 and c["eval_window"]), {})
    findings = {"headline_cell": headline, "cells": cells, "folds": folds,
                "secondary_parent_emergence": secondary,
                "meta": {"run_date": date.today().isoformat(),
                         "dev_window": [DEV_START, DEV_END],
                         "cost_bps_per_side": COST_BPS,
                         "n_boot": N_BOOT,
                         "registration": "DECISIONS.md 2026-07-07 H5",
                         "note": "2023+ rows flagged eval_window=false; "
                                 "trading seal applies."}}
    with open(lt.REPORTS / "findings_h5.json", "w") as f:
        json.dump(findings, f, indent=1, default=str)
    chart(indicators, mcom)
    log.info("HEADLINE (leather/search/6m): r=%s NW_t=%s boot_p=%s n=%s",
             headline.get("pearson_r"), headline.get("nw_t"),
             headline.get("block_boot_p"), headline.get("n"))
    for key, d in folds.items():
        log.info("folds %s: %s mean IR %s", key, d["folds"], d["mean_ir"])
    sig = [c for c in cells if c.get("eval_window") and
           c.get("block_boot_p") is not None and c["block_boot_p"] < 0.05]
    log.info("VERDICT: %d/%d dev cells pass boot p<0.05 after overlap "
             "correction; see findings_h5.json — every cell reported.",
             len(sig), sum(1 for c in cells if c.get("eval_window")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
