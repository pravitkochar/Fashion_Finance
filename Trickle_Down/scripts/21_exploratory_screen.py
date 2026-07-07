"""EXPLORATORY SCREEN — post-hoc, screening only (DECISIONS.md note applies).

Quick empirical read on five return-conviction channels to decide which, if
any, deserves a FULL pre-registered study. Simple statistics only (Spearman
ICs, lagged correlations, sign tests); no portfolio construction, no tuning.
Nothing here may be quoted as confirmatory — every number is exploratory by
construction (probes chosen after seeing prior results).

Probes (dev window 2017-01..2022-12, PIT via known_date):
  P1 monthly Spearman IC of {alignment level, alignment YoY, supplier
     material-demand z} vs forward {1,3,6}m excess returns (vs XRT)
  P2 runway-share z / trends z vs forward {3,6,9}m commodity returns
  P3 house emergence intensity vs forward {3,6}m parent excess returns
  P4 pre-earnings signal delta vs earnings-surprise sign (yfinance)
  P5 supplier material-demand z (lag 1-2q) vs revenue YoY (yfinance)

Output: reports/exploratory_screen.json + ranked table in the log.
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

import lib_trickle as lt

warnings.filterwarnings("ignore")
log = lt.get_logger("21_screen")

DEV_START, DEV_END = "2017-01", "2022-12"
MIN_MATS = 5


# ------------------------------------------------------------- loaders ------

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


def fwd_return(monthly: pd.DataFrame, k: int) -> pd.DataFrame:
    """Compound return over months m+1..m+k, indexed at m."""
    cum = (1 + monthly.fillna(0)).cumprod()
    fwd = cum.shift(-k) / cum - 1
    fwd[monthly.isna()] = np.nan
    return fwd


def load_mix():
    dm = lt.read_csv_or_empty(lt.DATA / "downstream_mix.csv")
    dm = dm[~dm["thin_sample"].astype(str).str.lower().eq("true")]
    dm = dm[dm["material"].isin(lt.signal_materials())].copy()
    dm["month"] = pd.PeriodIndex(dm["month"], freq="M")
    return dm


def season_vectors():
    rm = lt.read_csv_or_empty(lt.DATA / "runway_mix.csv")
    s = rm[(rm["level"] == "season")
           & rm["material"].isin(lt.signal_materials())].copy()
    s["known"] = pd.to_datetime(s["known_date"])
    return s


def alignment(dm, svec, retailer, month) -> float | None:
    sub = dm[(dm["retailer"] == retailer) & (dm["month"] == month)]
    if sub.empty:
        return None
    known = svec[svec["known"] <= month.end_time]
    if known.empty:
        return None
    season = known.loc[known["known"].idxmax(), "season_code"]
    rv = known[known["season_code"] == season].set_index("material")["share"]
    mv = sub.set_index("material")["share"]
    common = rv.index.intersection(mv.index)
    if len(common) < MIN_MATS or rv[common].std() == 0 or mv[common].std() == 0:
        return None
    return float(stats.spearmanr(rv[common], mv[common]).statistic)


def material_z(dm) -> pd.DataFrame:
    """Cross-retailer mean share per (month, material) -> trailing-12 z."""
    mean = (dm.groupby(["month", "material"])["share"].mean()
            .unstack().sort_index())
    mu = mean.shift(1).rolling(12, min_periods=8).mean()
    sd = mean.shift(1).rolling(12, min_periods=8).std(ddof=1)
    return (mean - mu) / sd.replace(0, np.nan)


def ic_series(sig: pd.DataFrame, fwd: pd.DataFrame) -> dict:
    ics = []
    for m in sig.index:
        if m not in fwd.index:
            continue
        row = pd.concat([sig.loc[m], fwd.loc[m]], axis=1, keys=["s", "r"]).dropna()
        if len(row) < 3 or row["s"].std() == 0:
            continue
        ics.append(stats.spearmanr(row["s"], row["r"]).statistic)
    ics = [i for i in ics if np.isfinite(i)]
    if len(ics) < 6:
        return {"mean_ic": None, "t": None, "n_months": len(ics)}
    arr = np.array(ics)
    return {"mean_ic": round(float(arr.mean()), 4),
            "t": round(float(arr.mean() / arr.std(ddof=1) * np.sqrt(len(arr))), 2),
            "n_months": len(arr)}


# -------------------------------------------------------------- probes ------

def p1(dm, svec, uni, m2, out):
    months = pd.period_range(DEV_START, DEV_END, freq="M")
    rmap = {r["key"]: r["ticker"] for r in uni["tier2_retailers"] if r["ticker"]}
    keys = sorted(set(dm["retailer"]) & set(rmap))
    align = pd.DataFrame({rmap[k]: {m: alignment(dm, svec, k, m) for m in months}
                          for k in keys}).T.astype(float).T
    align.index = months
    align_yoy = align - align.shift(12)

    mz = material_z(dm)
    smap = {s["ticker"]: s["materials"]
            for s in uni["tier3_suppliers"]}
    sup = pd.DataFrame({t: mz[[m for m in mats if m in mz.columns]].mean(axis=1)
                        for t, mats in smap.items()})
    sup = sup.reindex(months)

    xrt = m2["XRT"]
    excess = {k: fwd_return(m2, k).sub(fwd_return(xrt.to_frame("XRT"), k)["XRT"],
                                       axis=0) for k in (1, 3, 6)}
    res = {}
    for name, sig in [("alignment_level", align), ("alignment_yoy", align_yoy),
                      ("supplier_demand_z", sup)]:
        res[name] = {f"fwd{k}m": ic_series(sig, excess[k].reindex(columns=sig.columns))
                     for k in (1, 3, 6)}
    out["P1_ic"] = res


def p2(svec, m2, out):
    months = pd.period_range("2015-06", DEV_END, freq="M")
    # runway share z (season step-function -> trailing z)
    sv = svec.copy()
    sv["month"] = sv["known"].dt.to_period("M")
    rw = (sv.pivot_table(index="month", columns="material", values="share",
                         aggfunc="last").reindex(
              pd.period_range("2015-01", DEV_END, freq="M")).ffill())
    rz = (rw - rw.shift(1).rolling(36, min_periods=12).mean()) / \
         rw.shift(1).rolling(36, min_periods=12).std(ddof=1).replace(0, np.nan)
    tr = lt.read_csv_or_empty(lt.TRENDS / "trends.csv")
    tr = tr[tr["term_type"] == "material"].dropna(subset=["value_z"]).copy()
    tr["month"] = pd.to_datetime(tr["date"]).dt.to_period("M")
    tz = tr.pivot_table(index="month", columns="material", values="value_z",
                        aggfunc="mean")
    groups = {"CT=F": ["cotton", "denim"], "LE=F": ["leather"],
              "CL=F": ["polyester", "nylon"]}
    res = {}
    for com, mats in groups.items():
        if com not in m2.columns:
            continue
        for iname, panel in [("runway_z", rz), ("trends_z", tz)]:
            cols = [m for m in mats if m in panel.columns]
            if not cols:
                continue
            ind = panel[cols].mean(axis=1).reindex(months)
            for k in (3, 6, 9):
                fwd = fwd_return(m2[[com]], k)[com].reindex(months)
                pair = pd.concat([ind, fwd], axis=1).dropna()
                pair = pair[(pair.index >= DEV_START) & (pair.index <= DEV_END)]
                if len(pair) < 12:
                    res[f"{com}|{iname}|fwd{k}m"] = {"n": len(pair)}
                    continue
                r, p = stats.pearsonr(pair.iloc[:, 0], pair.iloc[:, 1])
                sign = float(((pair.iloc[:, 0] > 0) ==
                              (pair.iloc[:, 1] > 0)).mean())
                res[f"{com}|{iname}|fwd{k}m"] = {
                    "r": round(float(r), 3), "p": round(float(p), 3),
                    "sign_agree": round(sign, 3), "n": len(pair)}
    out["P2_commodity"] = res


def p3(uni, out):
    rm = lt.read_csv_or_empty(lt.DATA / "runway_mix.csv")
    b = rm[(rm["level"] == "brand")
           & rm["material"].isin(lt.signal_materials())].copy()
    b["skey"] = b["season_code"].map(lt.season_sort_key)
    # brand-level delta vs own trailing 3 seasons
    b = b.sort_values("skey")
    piv = b.pivot_table(index=["key", "season_code"], columns="material",
                        values="share", aggfunc="last")
    emerg = {}
    for brand in piv.index.get_level_values(0).unique():
        sub = piv.loc[brand].copy()
        sub = sub.loc[sorted(sub.index, key=lt.season_sort_key)]
        delta = sub - sub.shift(1).rolling(3, min_periods=3).mean()
        emerg[brand] = delta.clip(lower=0).sum(axis=1)
    parent = {h["slug"]: h["parent_ticker"] for h in uni["tier1_runway"]
              if h["parent_ticker"]}
    sys.path.insert(0, str(lt.PARENT_ROOT / "scripts"))
    import lib_event_study as les
    mpar = monthly_returns(lt.PARENT_PRICES)
    obs = []
    for brand, ser in emerg.items():
        tick = parent.get(brand)
        if not tick or tick not in mpar.columns:
            continue
        bench = les.TICKER_BENCH.get(tick)
        for season, e in ser.dropna().items():
            kd = lt.season_known_date(season)
            if not (date(2017, 1, 1) <= kd <= date(2022, 12, 31)):
                continue
            m = pd.Period(kd, freq="M")
            for k in (3, 6):
                fwd = fwd_return(mpar[[tick]], k)[tick].get(m, np.nan)
                fb = (fwd_return(mpar[[bench]], k)[bench].get(m, np.nan)
                      if bench in mpar.columns else
                      fwd_return(mpar, k).mean(axis=1).get(m, np.nan))
                if np.isfinite(fwd) and np.isfinite(fb):
                    obs.append({"k": k, "emerg": float(e),
                                "ex": float(fwd - fb)})
    res = {}
    df = pd.DataFrame(obs)
    for k in (3, 6):
        sub = df[df["k"] == k]
        if len(sub) < 12:
            res[f"fwd{k}m"] = {"n": len(sub)}
            continue
        r, p = stats.spearmanr(sub["emerg"], sub["ex"])
        res[f"fwd{k}m"] = {"spearman": round(float(r), 3),
                           "p": round(float(p), 3), "n": len(sub)}
    out["P3_parents"] = res


def p4(dm, svec, uni, out):
    import yfinance as yf
    mz = material_z(dm)
    smap = {s["ticker"]: s["materials"] for s in uni["tier3_suppliers"]}
    rows = []
    for tick in ["HM-B.ST", "3402.T", "IVL.BK", "LNZ.VI"]:
        try:
            ed = yf.Ticker(tick).earnings_dates
        except Exception as e:
            continue
        if ed is None or "Surprise(%)" not in ed.columns:
            continue
        for ts, row in ed.dropna(subset=["Surprise(%)"]).iterrows():
            m_prev = pd.Period(ts, freq="M") - 1
            if tick == "HM-B.ST":
                a1 = alignment(dm, svec, "hm", m_prev)
                a0 = alignment(dm, svec, "hm", m_prev - 12)
                sig = None if a1 is None or a0 is None else a1 - a0
            else:
                mats = [m for m in smap.get(tick, []) if m in mz.columns]
                cur = mz[mats].mean(axis=1)
                sig = (cur.get(m_prev, np.nan) - cur.get(m_prev - 12, np.nan))
                sig = None if not np.isfinite(sig) else float(sig)
            if sig is not None:
                rows.append({"ticker": tick, "date": str(ts.date()),
                             "sig": sig, "surprise": float(row["Surprise(%)"])})
    df = pd.DataFrame(rows)
    if df.empty:
        out["P4_surprise"] = {"n": 0}
        return
    agree = int(((df["sig"] > 0) == (df["surprise"] > 0)).sum())
    bt = stats.binomtest(agree, len(df), 0.5)
    out["P4_surprise"] = {"n": len(df), "agree": agree,
                          "agree_rate": round(agree / len(df), 3),
                          "binom_p": round(float(bt.pvalue), 3),
                          "note": "recent quarters only (yfinance window); "
                                  "mostly outside dev window"}


def p5(dm, uni, out):
    import yfinance as yf
    mz = material_z(dm)
    smap = {s["ticker"]: s["materials"] for s in uni["tier3_suppliers"]}
    res = {}
    for tick, mats in smap.items():
        try:
            q = yf.Ticker(tick).quarterly_income_stmt
            rev = q.loc["Total Revenue"].dropna().sort_index()
        except Exception:
            res[tick] = {"n": 0}
            continue
        rev.index = pd.PeriodIndex(rev.index, freq="Q")
        yoy = (rev / rev.shift(4) - 1).dropna()
        cols = [m for m in mats if m in mz.columns]
        ind = mz[cols].mean(axis=1)
        indq = ind.groupby(ind.index.asfreq("Q")).mean()
        for lag in (1, 2):
            pair = pd.concat([indq.shift(lag), yoy], axis=1).dropna()
            if len(pair) < 6:
                res[f"{tick}|lag{lag}q"] = {"n": len(pair)}
                continue
            r, p = stats.pearsonr(pair.iloc[:, 0], pair.iloc[:, 1])
            res[f"{tick}|lag{lag}q"] = {"r": round(float(r), 3),
                                        "p": round(float(p), 3),
                                        "n": len(pair)}
    out["P5_revenue"] = res


# ------------------------------------------------------------- ranking ------

def rank(out) -> list[dict]:
    rows = []

    def add(probe, key, t_like, n, extra=""):
        if t_like is None or not np.isfinite(t_like) or n is None:
            return
        score = abs(t_like) * min(1.0, (n or 0) / 12)
        rows.append({"probe": probe, "cell": key, "t_like": round(t_like, 2),
                     "n": n, "score": round(score, 2), "note": extra})

    for name, lags in out.get("P1_ic", {}).items():
        for k, d in lags.items():
            if d.get("t") is not None:
                add("P1", f"{name}|{k}", d["t"], d["n_months"],
                    f"IC {d['mean_ic']}")
    for key, d in out.get("P2_commodity", {}).items():
        if "r" in d:
            t = d["r"] * np.sqrt(max(d["n"] - 2, 1)) / np.sqrt(1 - d["r"] ** 2)
            add("P2", key, float(t), d["n"], f"r {d['r']}, sign {d['sign_agree']}")
    for key, d in out.get("P3_parents", {}).items():
        if "spearman" in d:
            r = d["spearman"]
            t = r * np.sqrt(max(d["n"] - 2, 1)) / np.sqrt(1 - r ** 2)
            add("P3", key, float(t), d["n"], f"rho {r}")
    d = out.get("P4_surprise", {})
    if d.get("n"):
        z = (d["agree"] - d["n"] / 2) / np.sqrt(d["n"] / 4)
        add("P4", "surprise_sign", float(z), d["n"], f"agree {d['agree_rate']}")
    for key, d in out.get("P5_revenue", {}).items():
        if "r" in d:
            t = d["r"] * np.sqrt(max(d["n"] - 2, 1)) / np.sqrt(1 - d["r"] ** 2)
            add("P5", key, float(t), d["n"], f"r {d['r']}")
    return sorted(rows, key=lambda x: -x["score"])


def main() -> int:
    lt.ensure_dirs()
    uni = lt.load_universe()
    dm = load_mix()
    svec = season_vectors()
    tickers = ([r["ticker"] for r in uni["tier2_retailers"] if r["ticker"]]
               + [s["ticker"] for s in uni["tier3_suppliers"]]
               + [c["ticker"] for c in uni["commodities"]] + ["XRT"])
    m2 = monthly_returns(lt.PRICES / "prices_tier23.csv", tickers)
    out: dict = {"label": "EXPLORATORY (post-hoc screen, non-confirmatory)",
                 "dev_window": [DEV_START, DEV_END]}
    for fn, args in [(p1, (dm, svec, uni, m2, out)), (p2, (svec, m2, out)),
                     (p3, (uni, out)), (p4, (dm, svec, uni, out)),
                     (p5, (dm, uni, out))]:
        try:
            fn(*args)
        except Exception as e:
            out[fn.__name__ + "_error"] = f"{type(e).__name__}: {e}"
            log.warning("%s failed: %s", fn.__name__, e)
    ranking = rank(out)
    out["ranking"] = ranking
    with open(lt.REPORTS / "exploratory_screen.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
    log.info("ranked cells (score = |t| x min(1, n/12)):")
    for r in ranking[:15]:
        log.info("  %-4s %-38s t=%-6s n=%-4s score=%-5s %s",
                 r["probe"], r["cell"], r["t_like"], r["n"], r["score"],
                 r["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
