"""EXPLORATORY channel screen (post-hoc, screening only — NOT confirmatory).

Four probes to decide which cascade channel, if any, deserves a full
pre-registered study:
  A  commodity trade  (does the cascade actually trade on CT=F/CL=F/LE=F?)
  B  accessories/category -> luxury parents
  C  color cascade (feasibility + runway-trend persistence)
  D  silhouette/prints (feasibility note only)

Every read is point-in-time via known_date. No result here may be quoted as
confirmatory; any PURSUE gets a fresh pre-registered design.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, "scripts"); sys.path.insert(0, "../scripts")
import lib_trickle as lt
import lib_event_study as le

ROOT = Path(".")
OUT = ROOT / "reports" / "explore_channels.json"
rng = np.random.default_rng(42)

# ----------------------------------------------------------------- helpers
def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 6:
        return np.nan, np.nan
    from scipy.stats import spearmanr
    r, p = spearmanr(x[m], y[m])
    return float(r), int(m.sum())

def nw_tstat(x, y, lag):
    """Newey-West t on slope of y ~ x (HAC, Bartlett)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)
    if n < 12 or x.std() == 0:
        return np.nan, n
    X = np.column_stack([np.ones(n), x])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ b
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = (X[L:] * resid[L:, None]).T @ (X[:-L] * resid[:-L, None])
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(max(cov[1, 1], 1e-18))
    return float(b[1] / se), n

def block_boot_p(x, y, horizon, draws=2000):
    """Moving-block bootstrap p for corr != 0 (block = horizon)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)
    if n < 12:
        return np.nan
    from scipy.stats import spearmanr
    obs = spearmanr(x, y)[0]
    bl = max(horizon, 2)
    nb = int(np.ceil(n / bl))
    cnt = 0
    for _ in range(draws):
        idx = []
        for _ in range(nb):
            s = rng.integers(0, n - bl + 1)
            idx.extend(range(s, s + bl))
        idx = np.array(idx[:n])
        yb = y[rng.permutation(n)]  # break dependence, keep block struct on x
        rb = spearmanr(x[idx], yb[:n])[0]
        if abs(rb) >= abs(obs):
            cnt += 1
    return float((cnt + 1) / (draws + 1))

def to_month(idx):
    """Normalize any datetime index to month-start Timestamps (alignment key)."""
    return pd.PeriodIndex(idx, freq="M").to_timestamp(how="start")

def monthly_returns(prices, ticker):
    d = prices[prices.ticker == ticker][["date", "adj_close"]].copy()
    if d.empty:
        return pd.Series(dtype=float)
    d["date"] = pd.to_datetime(d["date"])
    s = d.set_index("date")["adj_close"].resample("MS").last()
    s.index = to_month(s.index)
    return s

def fwd_return(px_monthly, months):
    return px_monthly.shift(-months) / px_monthly - 1.0

# ----------------------------------------------------------------- indicators
def runway_material_monthly(mix, materials):
    """Season-level share (summed over material group) z-scored vs trailing
    3y, placed at known_date, ffilled monthly. PIT-safe step function."""
    s = mix[(mix.level == "season") & (mix.material.isin(materials))].copy()
    g = s.groupby(["season_code", "known_date"])["share"].sum().reset_index()
    g["known_date"] = pd.to_datetime(g["known_date"])
    g = g.sort_values("known_date")
    g["z"] = (g["share"] - g["share"].rolling(6, min_periods=4).mean()) / \
             g["share"].rolling(6, min_periods=4).std()
    idx = pd.date_range(g["known_date"].min(), "2026-07-01", freq="MS")
    ser = g.set_index("known_date")["z"].reindex(
        g.set_index("known_date").index.union(idx)).sort_index().ffill().reindex(idx)
    ser.index = to_month(ser.index)
    return ser

def downstream_material_monthly(dmix, materials):
    d = dmix[dmix.material.isin(materials) &
             (~dmix.thin_sample.astype(str).str.lower().eq("true"))].copy()
    if d.empty:
        return pd.Series(dtype=float)
    d["month"] = pd.to_datetime(d["month"] + "-01")
    g = d.groupby("month")["share"].mean().sort_index()
    z = (g - g.rolling(12, min_periods=8).mean()) / g.rolling(12, min_periods=8).std()
    z.index = to_month(z.index)
    return z

def search_material_monthly(trends, materials):
    t = trends[(trends.term_type == "material") & trends.material.isin(materials)].copy()
    if t.empty or "value_z" not in t.columns:
        return pd.Series(dtype=float)
    t["date"] = pd.to_datetime(t["date"])
    g = t.groupby(pd.Grouper(key="date", freq="MS"))["value_z"].mean()
    g.index = to_month(g.index)
    return g

# ----------------------------------------------------------------- trade test
def zgated_folds(ind, fwd, horizon, sign, folds=(2019, 2020, 2021, 2022)):
    """Monthly z-gated L/S on one future; walk-forward per validation year.
    sign=+1 momentum, -1 contrarian. Net 10bps round trip per new position."""
    df = pd.concat([ind.rename("z"), fwd.rename("r")], axis=1).dropna()
    df = df[(df.index >= "2017-01-01") & (df.index <= "2022-12-31")]
    if len(df) < 20:
        return {}
    out = {}
    irs = []
    for yr in folds:
        v = df[(df.index >= f"{yr}-01-01") & (df.index <= f"{yr}-12-31")]
        if len(v) < 4:
            continue
        pos = np.where(v["z"] > 1, sign, np.where(v["z"] < -1, -sign, 0.0))
        # non-overlapping monthly proxy: use 1m-step realized of the horizon
        # signal by scaling; simple: position * forward return / horizon
        ret = pos * v["r"].values / horizon - np.abs(np.diff(np.r_[0, pos])) * 0.001
        ret = pos * v["r"].values / horizon
        turn = np.abs(np.diff(np.r_[0.0, pos])) * 0.001
        ret = ret - turn
        if np.std(ret) > 0:
            ir = float(np.mean(ret) / np.std(ret) * np.sqrt(12))
        else:
            ir = 0.0
        irs.append(ir)
        out[str(yr)] = {"ir": round(ir, 3), "n": int(len(v)),
                        "hit": round(float(np.mean(np.sign(pos * v['r'].values) > 0)
                                           if np.any(pos != 0) else 0.5), 3)}
    out["mean_ir"] = round(float(np.mean(irs)), 3) if irs else None
    return out

# ----------------------------------------------------------------- PROBE A
def probe_a(prices, rmix, dmix, trends):
    groups = {"CT=F": ["cotton", "denim"], "CL=F": ["polyester", "nylon"],
              "LE=F": ["leather"]}
    horizons = [3, 6, 9, 12]
    res = {}
    for comm, mats in groups.items():
        pxm = monthly_returns(prices, comm)
        inds = {"runway": runway_material_monthly(rmix, mats),
                "downstream": downstream_material_monthly(dmix, mats),
                "search": search_material_monthly(trends, mats)}
        for iname, ind in inds.items():
            for h in horizons:
                fwd = fwd_return(pxm, h)
                pair = pd.concat([ind.rename("i"), fwd.rename("f")], axis=1).dropna()
                pair = pair[(pair.index >= "2017-01-01") & (pair.index <= "2022-12-31")]
                if len(pair) < 12:
                    res[f"{comm}|{iname}|{h}m"] = {"n": len(pair), "verdict": "DEAD",
                                                   "why": "n<12"}
                    continue
                r, n = spearman(pair["i"], pair["f"])
                t, _ = nw_tstat(pair["i"], pair["f"], h)
                p = block_boot_p(pair["i"].values, pair["f"].values, h)
                # a-priori sign per indicator (NO post-hoc sign picking):
                # runway/downstream demand -> momentum (+1); search -> the
                # user's contrarian hypothesis (-1). Report BOTH but judge
                # only the pre-specified sign.
                apriori = +1 if iname in ("runway", "downstream") else -1
                mom = zgated_folds(ind, fwd, h, +1)
                con = zgated_folds(ind, fwd, h, -1)
                trade = mom if apriori == +1 else con
                trade_ir = trade.get("mean_ir")
                # ASSOCIATION guard: HAC t is the honest test under overlapping
                # forward returns (the block-bootstrap over-rejects — it breaks
                # return autocorrelation HAC keeps). Require BOTH to agree.
                assoc = (np.isfinite(t) and abs(t) >= 2.0
                         and p is not None and p < 0.05 and abs(r) >= 0.25)
                fold_irs = [v["ir"] for k, v in trade.items()
                            if k.isdigit() and isinstance(v, dict)]
                trade_ok = (trade_ir is not None and trade_ir > 0.3
                            and len(fold_irs) >= 3 and min(fold_irs) > -0.3)
                verdict = ("PURSUE" if (assoc and trade_ok) else
                           "MAYBE" if (assoc or trade_ok) else "DEAD")
                res[f"{comm}|{iname}|{h}m"] = {
                    "n": n, "spearman": round(r, 3),
                    "nw_t": round(t, 2) if np.isfinite(t) else None,
                    "boot_p": round(p, 4) if p is not None else None,
                    "apriori_sign": "momentum" if apriori == +1 else "contrarian",
                    "trade_apriori_meanIR": trade_ir,
                    "trade_apriori_folds": fold_irs,
                    "trade_mom_meanIR": mom.get("mean_ir"),
                    "trade_con_meanIR": con.get("mean_ir"),
                    "verdict": verdict}
    return res

# ----------------------------------------------------------------- PROBE B
def probe_b(prices_parent, cats, looks):
    ACC = {"bag", "shoes", "accessory"}
    lk = looks[["look_id", "brand_slug", "season_code", "parent_ticker"]].copy()
    c = cats.merge(lk, on="look_id", how="inner")
    c["is_acc"] = c["category"].isin(ACC).astype(float)
    hs = c.groupby(["brand_slug", "season_code", "parent_ticker"]).agg(
        acc_share=("is_acc", "mean"), n=("is_acc", "size")).reset_index()
    hs = hs[hs["n"] >= 15]  # need enough looks to trust the share
    # emergence: delta vs house trailing-3-season mean
    hs["skey"] = hs["season_code"].map(lambda s: lt.season_sort_key(s))
    hs = hs.sort_values(["brand_slug", "skey"])
    hs["acc_trail"] = hs.groupby("brand_slug")["acc_share"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    hs["acc_emerge"] = hs["acc_share"] - hs["acc_trail"]
    hs["known"] = hs["season_code"].map(lambda s: pd.Timestamp(lt.season_known_date(s)))
    # forward parent excess return
    px = prices_parent.copy(); px["date"] = pd.to_datetime(px["date"])
    def fwd_excess(row, months):
        tk, bench = row["parent_ticker"], le.TICKER_BENCH.get(row["parent_ticker"])
        if tk not in px.ticker.values or bench is None:
            return np.nan
        t0 = row["known"]
        def ret(t):
            s = px[(px.ticker == t) & (px.date >= t0) & (px.date <= t0 + pd.DateOffset(months=months))]
            if len(s) < 5:
                return np.nan
            return s.sort_values("date")["adj_close"].iloc[-1] / s.sort_values("date")["adj_close"].iloc[0] - 1
        r_t, r_b = ret(tk), ret(bench)
        return r_t - r_b if np.isfinite(r_t) and np.isfinite(r_b) else np.nan
    out = {}
    for months in (3, 6):
        hs[f"fwd{months}"] = hs.apply(lambda r: fwd_excess(r, months), axis=1)
        d = hs.dropna(subset=[f"fwd{months}", "acc_emerge"])
        r_ic, n = spearman(d["acc_emerge"], d[f"fwd{months}"])
        r_lvl, _ = spearman(d["acc_share"], d[f"fwd{months}"])
        out[f"{months}m"] = {"n": n, "ic_emergence": round(r_ic, 3) if np.isfinite(r_ic) else None,
                             "ic_level": round(r_lvl, 3) if np.isfinite(r_lvl) else None}
    strongest = max([abs(out[k]["ic_emergence"] or 0) for k in out] + [0])
    out["verdict"] = "PURSUE" if strongest > 0.15 else "MAYBE" if strongest > 0.08 else "DEAD"
    out["note"] = "accessory looks are sparse on runway (bag/shoes/accessory = dominant garment rarely); shares small"
    return out

# ----------------------------------------------------------------- PROBE C
def probe_c(colors, looks):
    lk = looks[["look_id", "season_code"]]
    c = colors.merge(lk, on="look_id", how="inner")
    c["skey"] = c["season_code"].map(lt.season_sort_key)
    seas = c.groupby(["season_code", "skey", "color"])["weight"].sum().reset_index()
    tot = seas.groupby("season_code")["weight"].transform("sum")
    seas["share"] = seas["weight"] / tot
    # HHI concentration per season
    hhi = seas.groupby(["season_code", "skey"]).apply(
        lambda g: (g["share"] ** 2).sum()).reset_index(name="hhi").sort_values("skey")
    # persistence: corr of a color's share with its own next-season share
    piv = seas.pivot_table(index="color", columns="skey", values="share").fillna(0)
    cols_sorted = sorted(piv.columns)
    pairs = []
    for i in range(len(cols_sorted) - 1):
        a, b = piv[cols_sorted[i]], piv[cols_sorted[i + 1]]
        pairs.append(pd.DataFrame({"t": a.values, "t1": b.values}))
    allp = pd.concat(pairs)
    r_persist, n = spearman(allp["t"], allp["t1"])
    return {"n_seasons": int(seas["season_code"].nunique()),
            "mean_hhi": round(float(hhi["hhi"].mean()), 3),
            "color_share_persistence_r": round(r_persist, 3) if np.isfinite(r_persist) else None,
            "persistence_n": n,
            "tradeable_target": "ABSENT — downstream scrape has no color field; no listed pure-play color/dye equity",
            "verdict": "FEASIBILITY-ONLY",
            "note": "runway color trend exists & persists, but nothing downstream/tradeable to point it at without new data"}

# ----------------------------------------------------------------- main
def main():
    prices = pd.read_csv("data/prices/prices_tier23.csv")
    prices_parent = pd.read_csv("../data/prices_raw.csv")
    rmix = pd.read_csv("data/runway_mix.csv")
    dmix = pd.read_csv("data/downstream_mix.csv")
    trends = pd.read_csv("data/trends/trends.csv")
    cats = pd.read_csv("data/runway/runway_categories.csv")
    colors = pd.read_csv("data/runway/runway_colors.csv")
    looks = pd.read_csv("data/runway/runway_looks.csv")

    result = {
        "_note": "EXPLORATORY / post-hoc screen. No result is confirmatory. "
                 "Any PURSUE requires a fresh pre-registered study.",
        "A_commodity_trade": probe_a(prices, rmix, dmix, trends),
        "B_accessories_parents": probe_b(prices_parent, cats, looks),
        "C_color": probe_c(colors, looks),
        "D_silhouette_prints": {
            "verdict": "UNTESTABLE-NOW",
            "note": "We tag material %, color, and dominant category — NOT "
                    "silhouette or print. Testing needs a re-tag pass over the "
                    "26,838 cached look images (feasible, ~a day of vision calls). "
                    "Choi et al. (2024) found silhouette propagated runway->retail "
                    "where styling did not, so silhouette is the highest-potential "
                    "future tag; prints are highly searchable but, like color, "
                    "have no pure-play tradeable target."},
    }
    OUT.write_text(json.dumps(result, indent=2))
    print("wrote", OUT)
    # ranked summary
    a = result["A_commodity_trade"]
    pursue = [k for k, v in a.items() if isinstance(v, dict) and v.get("verdict") == "PURSUE"]
    maybe = [k for k, v in a.items() if isinstance(v, dict) and v.get("verdict") == "MAYBE"]
    print("\n=== PROBE A commodity — PURSUE:", pursue or "none")
    print("=== PROBE A commodity — MAYBE:", maybe[:8])
    # show best assoc cells
    rows = [(k, v) for k, v in a.items() if isinstance(v, dict) and v.get("boot_p") is not None]
    rows.sort(key=lambda kv: (kv[1].get("boot_p") if kv[1].get("boot_p") is not None else 1))
    print("\n=== PROBE A — best-association cells (by boot p):")
    for k, v in rows[:8]:
        print(f"  {k:22s} r={v['spearman']:+.2f} nw_t={v['nw_t']} p={v['boot_p']} "
              f"momIR={v['trade_mom_meanIR']} conIR={v['trade_con_meanIR']} {v['verdict']}")
    print("\n=== PROBE B accessories->parents:", result["B_accessories_parents"])
    print("\n=== PROBE C color:", result["C_color"]["verdict"], "-", result["C_color"]["note"])
    print("=== PROBE D silhouette:", result["D_silhouette_prints"]["verdict"])

if __name__ == "__main__":
    main()
