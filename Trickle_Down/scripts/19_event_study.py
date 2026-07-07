"""H4 — earnings-window event study (pre-registered 2026-07-07, incl. the
same-day depth expansion: full robustness grid, permutation + pre-event
placebos, per-year folds, subsets, net-of-costs).

Construction (locked): per calendar quarter, pool that quarter's earnings
events; above/below-median signal -> long/short (quartiles when the quarter
has >=8 events); hold each position only over the event window around ITS
OWN earnings date; abnormal = ticker compounded return minus benchmark over
the same trading days.

Grid (every cell reported, headline = median / [-1,+1] / mix-alignment / XRT):
  split      {median, quartile}
  window     {[-1,+1], [0,+2]} trading days around the announcement
  signal     {mix_alignment_yoy (retailers), adoption_yoy (retailers),
              material_demand_yoy (suppliers)}
  benchmark  {XRT excess, local-index excess (XRT fallback where unmapped,
              flagged)}

Earnings dates: yfinance (FMP earnings endpoints are pay-walled on the
current key — probed 2026-07-07: v3 legacy 403, /stable 402). Cached to
data/earnings_dates.csv. Coverage disclosure in findings: ASC.L has no
historical dates on free sources -> the retailer sleeve is effectively
HM-B.ST; that limitation is reported, not hidden.

Dev window 2017-01..2022-12. --include-test is blocked behind the same
MODEL V2 FROZEN guard as 08_backtest.py.

Outputs: data/earnings_dates.csv, reports/event_study_h4.csv (headline
events), reports/findings_h4.json (grid/placebos/per_year/subsets/headline),
reports/img/h4_spreads.png.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

import lib_trickle as lt

m07 = importlib.import_module("07_signals")

log = lt.get_logger("19_event_study")

DEV_START, DEV_END = "2017-01-01", "2022-12-31"
COST_PER_SIDE = 0.002                     # 20 bps; round trip = 2 sides
NET_DRAG = 2 * COST_PER_SIDE              # per signed event
MIN_COMMON_MATERIALS = 6
N_PERMUTATIONS = 1000
EARN_CSV = lt.DATA / "earnings_dates.csv"

WINDOWS = {"[-1,+1]": (-1, 1), "[0,+2]": (0, 2)}
SPLITS = ("median", "quartile")
BENCHES = ("xrt", "local")
HEADLINE = ("median", "[-1,+1]", "mix_alignment_yoy", "xrt")


# ------------------------------------------------------------ earnings ------

def fetch_earnings(tickers: list[str]) -> pd.DataFrame:
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf
    cached = lt.read_csv_or_empty(EARN_CSV)
    rows, missing = [], []
    for t in tickers:
        if not cached.empty and (cached["ticker"] == t).any():
            continue
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=80)
            if ed is None or ed.empty:
                missing.append(t)
                continue
            for d in ed.index.tz_localize(None):
                rows.append({"ticker": t, "date": d.date().isoformat(),
                             "source": "yfinance"})
        except Exception as e:
            log.warning("earnings fetch failed %s: %s", t, str(e)[:80])
            missing.append(t)
    if rows:
        lt.upsert_csv(pd.DataFrame(rows), EARN_CSV,
                      keys=["ticker", "date"], sort_by=["ticker", "date"])
    if missing:
        log.warning("no earnings dates on free sources for: %s (disclosed)",
                    missing)
    out = lt.read_csv_or_empty(EARN_CSV)
    return out, missing


# ------------------------------------------------------------- signals ------

def solid_mix() -> pd.DataFrame:
    dm = lt.read_csv_or_empty(lt.DATA / "downstream_mix.csv")
    dm = dm[~dm["thin_sample"].astype(str).str.lower().eq("true")]
    return dm[dm["material"].isin(lt.signal_materials())].copy()


def runway_season_vectors() -> pd.DataFrame:
    rm = lt.read_csv_or_empty(lt.DATA / "runway_mix.csv")
    rm = rm[(rm["level"] == "season")
            & rm["material"].isin(lt.signal_materials())].copy()
    rm["known_date"] = pd.to_datetime(rm["known_date"])
    return rm


def _alignment(dm: pd.DataFrame, rm: pd.DataFrame, retailer: str,
               month: str) -> float | None:
    sub = dm[(dm["retailer"] == retailer) & (dm["month"] == month)]
    if sub.empty:
        return None
    month_start = pd.Timestamp(month + "-01")
    prior = rm[rm["known_date"] < month_start]
    if prior.empty:
        return None
    season = prior.loc[prior["known_date"].idxmax(), "season_code"]
    rvec = prior[prior["season_code"] == season].set_index("material")["share"]
    mvec = sub.set_index("material")["share"]
    mats = rvec.index.intersection(mvec.index)
    if len(mats) < MIN_COMMON_MATERIALS:
        return None
    a, b = mvec[mats].astype(float), rvec[mats].astype(float)
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _latest_solid_month(dm: pd.DataFrame, retailer: str,
                        before: pd.Timestamp) -> str | None:
    sub = dm[(dm["retailer"] == retailer)
             & (pd.to_datetime(dm["known_date"]) < before)]
    return None if sub.empty else sub["month"].max()


def sig_mix_alignment(dm, rm, retailer: str, T: pd.Timestamp) -> float | None:
    m = _latest_solid_month(dm, retailer, T)
    if m is None:
        return None
    m12 = str(pd.Period(m, freq="M") - 12)
    a_now = _alignment(dm, rm, retailer, m)
    a_then = _alignment(dm, rm, retailer, m12)
    if a_now is None or a_then is None:
        return None
    return a_now - a_then


def sig_adoption(store, key: str, T: pd.Timestamp) -> float | None:
    now = m07.adoption_score(store, key, T.date())
    then = m07.adoption_score(store, key, (T - timedelta(days=365)).date())
    if now is None or then is None or np.isnan(now) or np.isnan(then):
        return None
    return float(now - then)


def sig_material_demand(dm, materials: list[str],
                        T: pd.Timestamp) -> float | None:
    known = dm[pd.to_datetime(dm["known_date"]) < T]
    if known.empty:
        return None
    m = known["month"].max()
    m12 = str(pd.Period(m, freq="M") - 12)
    mean_share = known.groupby(["month", "material"])["share"].mean()
    deltas = []
    for mat in materials:
        try:
            deltas.append(mean_share[(m, mat)] - mean_share[(m12, mat)])
        except KeyError:
            continue
    return float(np.mean(deltas)) if deltas else None


# ------------------------------------------------------------- returns ------

def load_returns() -> pd.DataFrame:
    px = pd.read_csv(lt.PRICES / "prices_tier23.csv", parse_dates=["date"])
    return px.pivot_table(index="date", columns="ticker",
                          values="daily_return", aggfunc="last")


def window_abn(returns: pd.DataFrame, ticker: str, bench: str,
               edate: pd.Timestamp, w: tuple[int, int]) -> float | None:
    if ticker not in returns.columns or bench not in returns.columns:
        return None
    idx = returns.index
    pos = idx.searchsorted(edate)
    lo, hi = pos + w[0], pos + w[1]
    if lo < 0 or hi >= len(idx):
        return None
    win = returns.iloc[lo:hi + 1]
    tr, br = win[ticker].dropna(), win[bench].dropna()
    if len(tr) != (hi - lo + 1) or len(br) != (hi - lo + 1):
        return None
    return float((1 + tr).prod() - (1 + br).prod())


# ---------------------------------------------------------- evaluation ------

def assign_sides(ev: pd.DataFrame, split: str) -> pd.DataFrame:
    out = []
    for q, grp in ev.groupby("quarter"):
        g = grp.dropna(subset=["signal"]).copy()
        if len(g) < 2:
            continue
        if split == "quartile":
            if len(g) < 8:
                continue
            lo_q, hi_q = g["signal"].quantile([0.25, 0.75])
            g["side"] = np.where(g["signal"] >= hi_q, 1,
                                 np.where(g["signal"] <= lo_q, -1, 0))
        else:
            med = g["signal"].median()
            g["side"] = np.where(g["signal"] > med, 1,
                                 np.where(g["signal"] < med, -1, 0))
        out.append(g[g["side"] != 0])
    return (pd.concat(out, ignore_index=True)
            if out else pd.DataFrame(columns=list(ev.columns) + ["side"]))


def cell_metrics(sided: pd.DataFrame, abn_col: str) -> dict:
    d = sided.dropna(subset=[abn_col])
    if d.empty or d["side"].nunique() < 2:
        return {"status": "insufficient_events", "n_events": int(len(d))}
    signed = d["side"] * d[abn_col]
    longs, shorts = d[d["side"] == 1][abn_col], d[d["side"] == -1][abn_col]
    t, p = stats.ttest_1samp(signed, 0.0)
    return {"spread": round(float(longs.mean() - shorts.mean()), 5),
            "mean_signed": round(float(signed.mean()), 5),
            "mean_signed_net": round(float(signed.mean() - NET_DRAG), 5),
            "t_stat": round(float(t), 3), "p_value": round(float(p), 4),
            "hit_rate": round(float((signed > 0).mean()), 3),
            "n_events": int(len(d)), "n_long": int(len(longs)),
            "n_short": int(len(shorts))}


def permutation_p(sided: pd.DataFrame, abn_col: str, n: int) -> float | None:
    d = sided.dropna(subset=[abn_col]).copy()
    if d.empty:
        return None
    obs = float((d["side"] * d[abn_col]).mean())
    rng = np.random.default_rng(20260707)
    hits = 0
    for _ in range(n):
        perm = d.groupby("quarter")["side"].transform(
            lambda s: rng.permutation(s.values))
        if float((perm * d[abn_col]).mean()) >= obs:
            hits += 1
    return round(hits / n, 4)


# ---------------------------------------------------------------- main ------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-test", action="store_true")
    args = ap.parse_args()
    if args.include_test:
        decisions = (lt.ROOT / "DECISIONS.md").read_text(encoding="utf-8")
        if "MODEL V2 FROZEN" not in decisions:
            log.error("TEST WINDOW SEALED (same rule as 08).")
            return 2

    lt.ensure_dirs()
    uni = lt.load_universe()
    retailer_key = {r["ticker"]: r["key"] for r in uni["tier2_retailers"]
                    if r["ticker"]}
    supplier_mats = {s["ticker"]: s["materials"]
                     for s in uni["tier3_suppliers"]}
    bench_map = {**{r["ticker"]: r.get("bench")
                    for r in uni["tier2_retailers"] if r["ticker"]},
                 **{s["ticker"]: s.get("bench")
                    for s in uni["tier3_suppliers"]}}

    dm, rm = solid_mix(), runway_season_vectors()
    retailers_with_mix = [t for t, k in retailer_key.items()
                          if dm[dm["retailer"] == k]["month"].nunique() >= 13]
    tickers = retailers_with_mix + list(supplier_mats)
    earn, missing = fetch_earnings(tickers)
    earn["date"] = pd.to_datetime(earn["date"])
    earn = earn[(earn["date"] >= DEV_START) & (earn["date"] <= DEV_END)]
    log.info("earnings events in dev window: %s",
             earn.groupby("ticker").size().to_dict())

    store = m07.load_store()
    returns = load_returns()
    xrt = uni["benchmark_etf"]

    # ---- build event rows per signal type -------------------------------
    events = []
    for _, row in earn.iterrows():
        tk, T = row["ticker"], row["date"]
        sigs = {}
        if tk in retailer_key:
            key = retailer_key[tk]
            sigs["mix_alignment_yoy"] = sig_mix_alignment(dm, rm, key, T)
            if store is not None:
                sigs["adoption_yoy"] = sig_adoption(store, key, T)
        if tk in supplier_mats:
            sigs["material_demand_yoy"] = sig_material_demand(
                dm, supplier_mats[tk], T)
        for sname, sval in sigs.items():
            if sval is None:
                continue
            ev = {"ticker": tk, "edate": T, "signal_type": sname,
                  "signal": sval, "quarter": f"{T.year}Q{(T.month-1)//3+1}"}
            for wname, w in WINDOWS.items():
                ev[f"abn_xrt_{wname}"] = window_abn(returns, tk, xrt, T, w)
                local = bench_map.get(tk) or xrt
                ev[f"abn_local_{wname}"] = window_abn(returns, tk, local, T, w)
                ev[f"local_fallback"] = bench_map.get(tk) is None
            # pre-event placebo window [-10,-8]
            ev["abn_xrt_placebo"] = window_abn(returns, tk, xrt, T, (-10, -8))
            events.append(ev)
    ev_df = pd.DataFrame(events)
    if ev_df.empty:
        log.error("no computable events — check coverage")
        return 1
    log.info("computable events by signal: %s",
             ev_df.groupby("signal_type").size().to_dict())

    # ---- the full grid ---------------------------------------------------
    findings = {"grid": {}, "meta": {
        "dev_window": [DEV_START, DEV_END],
        "headline_cell": "/".join(HEADLINE),
        "earnings_missing_free": missing,
        "retailer_sleeve_note": "ASC.L lacks historical earnings dates on "
                                "free sources; retailer signals are "
                                "effectively HM-B.ST only (disclosed).",
        "cost_bps_per_side": 20, "n_permutations": N_PERMUTATIONS}}
    headline_sided = None
    for sname in ev_df["signal_type"].unique():
        base = ev_df[ev_df["signal_type"] == sname]
        for split in SPLITS:
            sided = assign_sides(base, split)
            for wname in WINDOWS:
                for bench in BENCHES:
                    col = f"abn_{bench}_{wname}"
                    key = f"{split}/{wname}/{sname}/{bench}"
                    findings["grid"][key] = cell_metrics(sided, col)
                    if (split, wname, sname, bench) == HEADLINE:
                        headline_sided = sided.copy()
                        headline_col = col

    # ---- headline extras: placebos, per-year, subsets --------------------
    if headline_sided is not None and not headline_sided.empty:
        findings["headline"] = findings["grid"]["/".join(HEADLINE)]
        findings["placebos"] = {
            "permutation_p_one_sided": permutation_p(
                headline_sided, headline_col, N_PERMUTATIONS),
            "pre_event_window_[-10,-8]": cell_metrics(
                headline_sided, "abn_xrt_placebo")}
        per_year = {}
        for y, g in headline_sided.groupby(headline_sided["edate"].dt.year):
            per_year[int(y)] = cell_metrics(g, headline_col)
        findings["per_year"] = per_year
        headline_sided.to_csv(lt.REPORTS / "event_study_h4.csv", index=False)
    # subsets at headline params (mix-alignment IS retailer-only; supplier
    # subset = material_demand at the same split/window/bench)
    findings["subsets"] = {
        "retailer_only": findings["grid"].get(
            "median/[-1,+1]/mix_alignment_yoy/xrt"),
        "supplier_only": findings["grid"].get(
            "median/[-1,+1]/material_demand_yoy/xrt")}

    with open(lt.REPORTS / "findings_h4.json", "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)

    # ---- chart ------------------------------------------------------------
    if headline_sided is not None and not headline_sided.empty:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
        py = {y: v.get("mean_signed") for y, v in
              findings.get("per_year", {}).items()
              if isinstance(v, dict) and v.get("mean_signed") is not None}
        ax1.bar([str(k) for k in py], list(py.values()), color="#3E6FB0")
        ax1.axhline(0, color="#888", lw=0.8)
        ax1.set_title("H4 mean signed abnormal (headline), by year")
        signed = (headline_sided["side"]
                  * headline_sided[headline_col]).dropna()
        ax2.hist(signed, bins=24, color="#B5762E", alpha=0.85)
        ax2.axvline(signed.mean(), color="#B6382E", lw=1.4)
        ax2.set_title(f"per-event signed abn (n={len(signed)})")
        fig.tight_layout()
        fig.savefig(lt.REPORTS / "img" / "h4_spreads.png", dpi=120)
        plt.close(fig)

    h = findings.get("headline", {})
    log.info("VERDICT H4 headline: spread=%s mean_signed=%s (net %s) t=%s "
             "p=%s perm_p=%s hit=%s n=%s",
             h.get("spread"), h.get("mean_signed"),
             h.get("mean_signed_net"), h.get("t_stat"), h.get("p_value"),
             findings.get("placebos", {}).get("permutation_p_one_sided"),
             h.get("hit_rate"), h.get("n_events"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
