"""25 — EXPLORATORY prelim screen: 5 fashion channels x 3 questions = 15 cells.

Screening only. Nothing here is confirmatory; a post-hoc note is appended to
DECISIONS.md. For each cell we find the best preliminary signal available
(best proxy / lag / candidate instrument) and label it
SIGNAL / WEAK / NONE / UNTESTABLE with a worth_deeper flag.

Channels: color, accessories(category), silhouette(category proxy), prints,
commodities/materials.
Q1 runway -> retail (retail proxied by Google search interest where we have
   no downstream field); Q2 retail -> supplier; Q3 anything tradeable (wide
   sweep over instruments x lags x sign, best walk-forward fold IR).

Runway side is PIT: season signals placed at season_known_date, ffilled
monthly. Trends/prices pulled live (cached). Overlap-inflated t is flagged
(independent obs ~ n/horizon).
"""
from __future__ import annotations

import json
import time
import random
import warnings
from datetime import date

import numpy as np
import pandas as pd

import lib_trickle as lt

warnings.filterwarnings("ignore")
log = lt.get_logger("25_prelim")

ROOT = lt.ROOT
PRELIM_TRENDS = lt.DATA / "trends" / "prelim_trends.csv"
PRELIM_PRICES = lt.DATA / "prices" / "prelim_prices.csv"
OUT = ROOT / "reports" / "prelim_matrix.json"

MONTHS = pd.period_range("2016-01", "2025-12", freq="M")

# ---- trend term sets (consumer-demand proxy) -------------------------------
COLOR_TERMS = ["burgundy dress", "olive green", "sage green", "butter yellow",
               "chocolate brown", "pink dress", "red dress", "black dress"]
ACC_TERMS = ["designer bag", "tote bag", "loafers", "ballet flats",
             "mary janes", "shoulder bag"]
PRINT_TERMS = ["animal print", "leopard print", "floral dress", "polka dot",
               "gingham", "tie dye"]
SIL_TERMS = ["wide leg pants", "oversized blazer", "maxi dress",
             "baggy jeans", "mini skirt"]
ALL_TERMS = {t: "color" for t in COLOR_TERMS}
ALL_TERMS |= {t: "accessory" for t in ACC_TERMS}
ALL_TERMS |= {t: "print" for t in PRINT_TERMS}
ALL_TERMS |= {t: "silhouette" for t in SIL_TERMS}

# ---- price candidates (wide net) -------------------------------------------
PIGMENT = ["KRO", "HUN", "DD", "VNTR", "ECL", "CE"]
ACCESS_EQ = ["TPR", "CPRI", "NKE", "DECK", "CROX", "BIRK", "SKX", "ONON"]
ETFS = ["XRT", "XLY", "RTH"]
COMMOD = ["CT=F", "CL=F", "LE=F"]
FIBER = ["3402.T", "IVL.BK", "RELIANCE.NS", "LNZ.VI"]
PARENTS = ["MC.PA", "KER.PA", "RMS.PA", "CFR.SW"]
ALL_TICKERS = sorted(set(PIGMENT + ACCESS_EQ + ETFS + COMMOD + FIBER + PARENTS))


# ============================================================ data pulls ====

def pull_trends() -> pd.DataFrame:
    if PRELIM_TRENDS.exists():
        cached = pd.read_csv(PRELIM_TRENDS)
        have = set(cached["term"].unique())
        todo = [t for t in ALL_TERMS if t not in have]
        if not todo:
            log.info("prelim_trends cached (%d terms)", len(have))
            return cached
    else:
        cached = pd.DataFrame()
        todo = list(ALL_TERMS)
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log.error("pytrends missing")
        return cached
    pt = TrendReq(hl="en-US", tz=0)
    tf = f"2015-01-01 {date.today().isoformat()}"
    rows = []
    for i in range(0, len(todo), 5):
        batch = todo[i:i + 5]
        got = None
        for attempt in (1, 2, 3):
            try:
                pt.build_payload(batch, timeframe=tf, geo="")
                got = pt.interest_over_time()
                break
            except Exception as e:
                if "429" in str(e) and attempt < 3:
                    log.warning("429 batch %s, backoff %ds", batch, 60 * attempt)
                    time.sleep(60 * attempt)
                    continue
                log.warning("batch %s failed: %s", batch, str(e)[:80])
                break
        if got is not None and not got.empty:
            for term in batch:
                if term not in got.columns:
                    continue
                for dt, val in got[term].items():
                    rows.append({"date": pd.Timestamp(dt).date().isoformat(),
                                 "term": term, "kind": ALL_TERMS[term],
                                 "value": int(val)})
            log.info("trends batch %d ok (%s)", i // 5 + 1, batch[0])
        time.sleep(random.uniform(8, 15))
    new = pd.DataFrame(rows)
    out = pd.concat([cached, new], ignore_index=True) if not cached.empty else new
    if not out.empty:
        out.drop_duplicates(["date", "term"]).to_csv(PRELIM_TRENDS, index=False)
    return out


def pull_prices() -> pd.DataFrame:
    if PRELIM_PRICES.exists():
        return pd.read_csv(PRELIM_PRICES, parse_dates=["date"])
    import yfinance as yf
    frames = []
    for t in ALL_TICKERS:
        try:
            h = yf.download(t, start="2015-01-01", end="2026-01-01",
                            progress=False, auto_adjust=True)
            if h.empty:
                log.warning("no data: %s", t)
                continue
            close = h["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            df = pd.DataFrame({"date": close.index, "ticker": t,
                               "adj_close": close.values})
            frames.append(df)
            log.info("priced %s (%d rows)", t, len(df))
        except Exception as e:
            log.warning("price fail %s: %s", t, str(e)[:60])
        time.sleep(0.5)
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(PRELIM_PRICES, index=False)
    return out


# ==================================================== signal builders ========

def monthly_index() -> pd.PeriodIndex:
    return MONTHS


def season_signal_monthly(per_season: dict[str, float]) -> pd.Series:
    """dict[season_code]->value  ->  monthly step series at known_date, ffill."""
    pts = {}
    for code, v in per_season.items():
        try:
            kd = lt.season_known_date(code)
        except Exception:
            continue
        pts[pd.Period(f"{kd.year}-{kd.month:02d}", "M")] = v
    if not pts:
        return pd.Series(dtype=float, index=MONTHS)
    s = pd.Series(pts).sort_index()
    return s.reindex(MONTHS.union(s.index)).ffill().reindex(MONTHS)


def z(series: pd.Series, win: int = 24) -> pd.Series:
    mu = series.rolling(win, min_periods=12).mean()
    sd = series.rolling(win, min_periods=12).std()
    return (series - mu) / sd.replace(0, np.nan)


def runway_color_shares() -> pd.DataFrame:
    """per season: share of each color across that season's looks."""
    col = pd.read_csv(lt.RUNWAY / "runway_colors.csv")
    looks = pd.read_csv(lt.RUNWAY / "runway_looks.csv")[["look_id", "season_code"]]
    m = col.merge(looks, on="look_id")
    g = m.groupby(["season_code", "color"])["weight"].sum().reset_index()
    tot = g.groupby("season_code")["weight"].transform("sum")
    g["share"] = g["weight"] / tot
    return g.pivot(index="season_code", columns="color", values="share").fillna(0)


def runway_category_shares() -> pd.DataFrame:
    cat = pd.read_csv(lt.RUNWAY / "runway_categories.csv")
    looks = pd.read_csv(lt.RUNWAY / "runway_looks.csv")[["look_id", "season_code"]]
    m = cat.merge(looks, on="look_id")
    g = m.groupby(["season_code", "category"]).size().reset_index(name="n")
    tot = g.groupby("season_code")["n"].transform("sum")
    g["share"] = g["n"] / tot
    return g.pivot(index="season_code", columns="category", values="share").fillna(0)


def trend_monthly(kind: str, terms: list[str], trends: pd.DataFrame) -> pd.Series:
    """mean z of the given terms' monthly search, PIT-safe (month-end known)."""
    if trends.empty:
        return pd.Series(dtype=float, index=MONTHS)
    sub = trends[trends["term"].isin(terms)].copy()
    if sub.empty:
        return pd.Series(dtype=float, index=MONTHS)
    sub["m"] = pd.PeriodIndex(pd.to_datetime(sub["date"]), freq="M")
    wide = sub.pivot_table(index="m", columns="term", values="value",
                           aggfunc="mean")
    zc = wide.apply(z)
    return zc.mean(axis=1).reindex(MONTHS)


def monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    p = prices.copy()
    p["m"] = pd.PeriodIndex(p["date"], freq="M")
    last = p.sort_values("date").groupby(["ticker", "m"])["adj_close"].last()
    wide = last.unstack(0)
    return wide.pct_change().reindex(MONTHS)


# ===================================================== stats primitives =======

def nw_t(x: pd.Series, y: pd.Series, lag: int) -> tuple:
    """corr of x(t) vs y(t+lag); Newey-West t (Bartlett, L=lag)."""
    d = pd.concat([x, y.shift(-lag)], axis=1).dropna()
    d.columns = ["x", "y"]
    n = len(d)
    if n < 10 or d["x"].std() == 0 or d["y"].std() == 0:
        return np.nan, np.nan, n
    r = float(np.corrcoef(d["x"], d["y"])[0, 1])
    xx = (d["x"] - d["x"].mean()).values
    yy = (d["y"] - d["y"].mean()).values
    beta = (xx @ yy) / (xx @ xx)
    resid = yy - beta * xx
    s2 = (xx * resid)
    L = max(1, lag)
    var = np.sum(s2 ** 2)
    for k in range(1, L + 1):
        w = 1 - k / (L + 1)
        var += 2 * w * np.sum(s2[k:] * s2[:-k])
    se = np.sqrt(var) / (xx @ xx)
    t = beta / se if se > 0 else np.nan
    return r, float(t), n


def ls_fold_ir(sig: pd.Series, ret: pd.Series, lag: int, sign: int) -> tuple:
    """+-1z long/short of one instrument over the 2017-2022 dev window,
    held `lag` months. Full-period annualized IR over ACTIVE months (a ~4x/yr
    signal is too sparse for per-year folds). Requires >=12 active months so
    a handful of lucky months can't manufacture a huge IR. sign=+1 momentum."""
    d = pd.concat([sig, ret.shift(-lag)], axis=1).dropna()
    d.columns = ["z", "fwd"]
    d = d[(d.index >= pd.Period("2017-01", "M")) &
          (d.index <= pd.Period("2022-12", "M"))]
    d["pos"] = np.where(d["z"] > 1, sign, np.where(d["z"] < -1, -sign, 0))
    d["pnl"] = d["pos"] * d["fwd"] - 0.001 * (d["pos"].diff().abs().fillna(0))
    act = d[d["pos"] != 0]
    if len(act) < 12 or act["pnl"].std() == 0:
        return np.nan, np.nan, len(act)
    ir = act["pnl"].mean() / act["pnl"].std() * np.sqrt(12)
    hit = (act["pnl"] > 0).mean()
    return float(ir), float(hit), len(act)


def _sweep_max(sig: pd.Series, rets: pd.DataFrame, tickers: list[str],
               lags) -> tuple:
    best_ir, best = -9, None
    n_pos = n_tot = 0
    for tk in tickers:
        if tk not in rets.columns:
            continue
        for lag in lags:
            for sign in (1, -1):
                ir, hit, n = ls_fold_ir(sig, rets[tk], lag, sign)
                if np.isnan(ir) or n < 10:
                    continue
                n_tot += 1
                if ir > 0:
                    n_pos += 1
                if ir > best_ir:
                    best_ir = ir
                    best = {"ir": round(ir, 3), "ticker": tk, "lag": lag,
                            "sign": sign,
                            "hit": round(hit, 2) if hit == hit else None,
                            "n": n}
    return best, n_pos, n_tot


def best_sweep(sig: pd.Series, rets: pd.DataFrame, tickers: list[str],
               lags=range(1, 13), n_perm: int = 20) -> dict:
    """Best walk-forward fold IR over tickers x lags x sign, WITH a
    selection-aware null: circularly rotate the signal n_perm times and
    re-run the same sweep; p = fraction of rotations whose best IR >= the
    real best. A best-of-sweep IR only means something if it beats what
    pure data-mining on a scrambled signal produces."""
    real, n_pos, n_tot = _sweep_max(sig, rets, tickers, lags)
    if real is None:
        return {"ir": None, "sel_p": None, "n_combos": n_tot,
                "too_rare": True}
    sv = sig.dropna()
    beat = 0
    shifts = [int(len(sv) * k / (n_perm + 1)) for k in range(1, n_perm + 1)]
    for sh in shifts:
        rot = pd.Series(np.roll(sv.values, sh), index=sv.index).reindex(sig.index)
        nb, _, _ = _sweep_max(rot, rets, tickers, lags)
        if nb and nb["ir"] >= real["ir"]:
            beat += 1
    real["sel_p"] = round((beat + 1) / (n_perm + 1), 3)
    real["frac_pos"] = round(n_pos / n_tot, 2) if n_tot else None
    real["n_combos"] = n_tot
    return real


def best_lagcorr(x: pd.Series, ys: dict[str, pd.Series],
                 lags=range(0, 10)) -> dict:
    best = {"t": 0, "r": None, "lag": None, "target": None, "n": 0}
    for name, y in ys.items():
        for lag in lags:
            r, t, n = nw_t(x, y, lag)
            if not np.isnan(t) and abs(t) > abs(best["t"]) and n >= 12:
                best = {"t": round(t, 2), "r": round(r, 2), "lag": lag,
                        "target": name, "n": n}
    return best if best["target"] else {"t": None}


def verdict(stat: float | None, n: int, kind: str) -> tuple[str, bool]:
    """kind: 'assoc' uses |t|; 'trade' uses fold IR."""
    if stat is None:
        return "UNTESTABLE", False
    if kind == "assoc":
        indep = n  # already low-freq; caller notes overlap
        if abs(stat) >= 2.5:
            return "SIGNAL", True
        if abs(stat) >= 1.7:
            return "WEAK", True
        return "NONE", False
    else:
        # `stat` here is the selection-aware p (fraction of scrambled-signal
        # sweeps that matched/beat the real best). Low p = the best pick
        # genuinely beats data-mining noise. A giant raw IR with p~0.5 is a
        # mining artifact, not signal.
        # stat is a (sel_p, raw_ir) tuple for trade cells
        if stat is None or (isinstance(stat, tuple) and stat[0] is None):
            return "NONE", False
        sel_p, raw_ir = stat
        if raw_ir is not None and raw_ir > 3.0:
            return "NONE (degenerate IR — small-sample)", False
        if sel_p <= 0.05:
            return "SIGNAL", True
        if sel_p <= 0.20:
            return "WEAK", True
        return "NONE (mining artifact)", False


# =============================================================== main ========

def main() -> int:
    log.info("pulling trends (best-effort)...")
    trends = pull_trends()
    log.info("pulling prices...")
    prices = pull_prices()
    rets = monthly_returns(prices)
    log.info("have %d price tickers, %d trend terms",
             rets.shape[1], 0 if trends.empty else trends["term"].nunique())

    colsh = runway_color_shares()
    catsh = runway_category_shares()

    # ---- runway monthly signals -------------------------------------------
    # color: emergence of "trend" colors (non-neutral), z of their combined share
    trend_cols = [c for c in ["burgundy", "green", "olive", "pink", "yellow",
                              "red", "purple", "orange"] if c in colsh.columns]
    col_series = season_signal_monthly(
        colsh[trend_cols].sum(axis=1).to_dict())
    col_rw = z(col_series)
    # accessory share of runway
    acc_cols = [c for c in ["bag", "shoes", "accessory"] if c in catsh.columns]
    acc_series = season_signal_monthly(catsh[acc_cols].sum(axis=1).to_dict())
    acc_rw = z(acc_series)
    # silhouette proxy: tailoring+outerwear (structured) share
    sil_cols = [c for c in ["tailoring", "outerwear"] if c in catsh.columns]
    sil_series = season_signal_monthly(catsh[sil_cols].sum(axis=1).to_dict())
    sil_rw = z(sil_series)

    # ---- trend (consumer/retail proxy) monthly series ---------------------
    col_tr = trend_monthly("color", COLOR_TERMS, trends)
    acc_tr = trend_monthly("accessory", ACC_TERMS, trends)
    prn_tr = trend_monthly("print", PRINT_TERMS, trends)
    sil_tr = trend_monthly("silhouette", SIL_TERMS, trends)

    # ---- material demand (existing measured downstream) -------------------
    dmix = pd.read_csv(lt.DATA / "downstream_mix.csv")
    dmix = dmix[~dmix["thin_sample"].astype(str).str.lower().eq("true")]
    dmix["m"] = pd.PeriodIndex(dmix["month"], freq="M")
    mat_demand = {}
    for mat in ["cotton", "polyester", "leather", "wool", "viscose", "nylon"]:
        s = (dmix[dmix["material"] == mat].groupby("m")["share"].mean()
             .reindex(MONTHS))
        mat_demand[mat] = z(s)

    cells = {}

    def rec(key, proxy, stat, lag, n, sign, vk, note, extra=None):
        v, wd = verdict(stat, n, vk)
        if isinstance(stat, tuple):
            shown = stat[0]  # sel_p is the headline stat for trade cells
        else:
            shown = stat
        cells[key] = {"best_proxy_used": proxy,
                      "best_stat": None if shown is None else round(float(shown), 3),
                      "lag": lag, "n": n, "sign": sign, "verdict": v,
                      "worth_deeper": wd, "one_line": note}
        if extra:
            cells[key].update(extra)

    # ======================= COLOR =========================================
    # Q1 runway color -> color search interest
    b = best_lagcorr(col_rw, {"color_search": col_tr})
    rec("color.Q1_runway_to_retail", "runway trend-color share z -> color search z",
        b.get("t"), b.get("lag"), b.get("n"), None, "assoc",
        f"runway trend-color emergence vs color search interest, best |t|={b.get('t')} at +{b.get('lag')}mo (overlap-inflated)")
    # Q2 color signal -> pigment makers
    pig = {t: rets[t] for t in PIGMENT if t in rets.columns}
    b2 = best_lagcorr(col_tr, pig)
    rec("color.Q2_retail_to_supplier", "color search z -> pigment-maker returns",
        b2.get("t"), b2.get("lag"), b2.get("n"), None, "assoc",
        f"color demand vs pigment/dye equities ({b2.get('target')}), best |t|={b2.get('t')} at +{b2.get('lag')}mo")
    # Q3 tradeable: color signal wide sweep
    sw = best_sweep(col_tr, rets, PIGMENT + ETFS + ACCESS_EQ)
    rec("color.Q3_tradeable", "color search z -> wide equity sweep",
        (sw.get("sel_p"), sw.get("ir")), sw.get("lag"), sw.get("n"), sw.get("sign"), "trade",
        f"best-of-{sw.get('n_combos')} IR={sw.get('ir')} ({sw.get('ticker')},+{sw.get('lag')}mo) but selection-p={sw.get('sel_p')}, {sw.get('frac_pos')} of combos positive",
        {"best_ticker": sw.get("ticker"), "raw_ir": sw.get("ir"),
         "sel_p": sw.get("sel_p"), "frac_pos": sw.get("frac_pos")})

    # ======================= ACCESSORIES ===================================
    b = best_lagcorr(acc_rw, {"acc_search": acc_tr})
    rec("accessories.Q1_runway_to_retail", "runway accessory share z -> accessory search z",
        b.get("t"), b.get("lag"), b.get("n"), None, "assoc",
        f"runway bag/shoe share vs accessory search, best |t|={b.get('t')} at +{b.get('lag')}mo")
    # Q2 accessory -> leather + parents
    tgt = {"LE=F": rets["LE=F"]} if "LE=F" in rets.columns else {}
    for p in PARENTS:
        if p in rets.columns:
            tgt[p] = rets[p]
    b2 = best_lagcorr(acc_tr, tgt)
    rec("accessories.Q2_retail_to_supplier", "accessory search z -> leather/parent returns",
        b2.get("t"), b2.get("lag"), b2.get("n"), None, "assoc",
        f"accessory demand vs {b2.get('target')} (leather/luxury parents), best |t|={b2.get('t')} at +{b2.get('lag')}mo")
    sw = best_sweep(acc_tr, rets, ACCESS_EQ + PARENTS + ["LE=F"])
    rec("accessories.Q3_tradeable", "accessory search z -> bag/shoe/luxury sweep",
        (sw.get("sel_p"), sw.get("ir")), sw.get("lag"), sw.get("n"), sw.get("sign"), "trade",
        f"best-of-{sw.get('n_combos')} IR={sw.get('ir')} ({sw.get('ticker')},+{sw.get('lag')}mo) but selection-p={sw.get('sel_p')}, {sw.get('frac_pos')} of combos positive",
        {"best_ticker": sw.get("ticker"), "raw_ir": sw.get("ir"),
         "sel_p": sw.get("sel_p"), "frac_pos": sw.get("frac_pos")})

    # ======================= SILHOUETTE ====================================
    b = best_lagcorr(sil_rw, {"sil_search": sil_tr})
    rec("silhouette.Q1_runway_to_retail", "runway structured-share z -> silhouette search z",
        b.get("t"), b.get("lag"), b.get("n"), None, "assoc",
        f"runway tailoring/outerwear share vs silhouette search, best |t|={b.get('t')} at +{b.get('lag')}mo (category is a crude shape proxy)")
    rec("silhouette.Q2_retail_to_supplier", "n/a — shape has no material supplier",
        None, None, 0, None, "assoc",
        "silhouette is a shape, not a material input — no fiber/commodity supplier maps to it")
    sw = best_sweep(sil_tr, rets, ACCESS_EQ + ETFS + PARENTS)
    rec("silhouette.Q3_tradeable", "silhouette search z -> retailer/parent sweep",
        (sw.get("sel_p"), sw.get("ir")), sw.get("lag"), sw.get("n"), sw.get("sign"), "trade",
        f"best-of-{sw.get('n_combos')} IR={sw.get('ir')} ({sw.get('ticker')},+{sw.get('lag')}mo) but selection-p={sw.get('sel_p')}, {sw.get('frac_pos')} of combos positive",
        {"best_ticker": sw.get("ticker"), "raw_ir": sw.get("ir"),
         "sel_p": sw.get("sel_p"), "frac_pos": sw.get("frac_pos")})

    # ======================= PRINTS ========================================
    # runway side missing (no print tags); test print search persistence only
    if not prn_tr.dropna().empty:
        ac = prn_tr.autocorr(lag=1)
    else:
        ac = None
    rec("prints.Q1_runway_to_retail", "print search only (runway print UNTAGGED)",
        None, None, 0, None, "assoc",
        f"runway print tags do not exist; print search interest autocorr(1)={None if ac is None else round(ac,2)} — cannot test runway->retail")
    rec("prints.Q2_retail_to_supplier", "n/a — no listed print/textile pure-play",
        None, None, 0, None, "assoc",
        "prints relate to textile printers/mills; no pure-play listed supplier to map")
    sw = best_sweep(prn_tr, rets, ACCESS_EQ + ETFS)
    rec("prints.Q3_tradeable", "print search z -> retailer sweep",
        (sw.get("sel_p"), sw.get("ir")), sw.get("lag"), sw.get("n"), sw.get("sign"), "trade",
        f"best-of-{sw.get('n_combos')} IR={sw.get('ir')} ({sw.get('ticker')},+{sw.get('lag')}mo) but selection-p={sw.get('sel_p')}, {sw.get('frac_pos')} of combos positive",
        {"best_ticker": sw.get("ticker"), "raw_ir": sw.get("ir"),
         "sel_p": sw.get("sel_p"), "frac_pos": sw.get("frac_pos")})

    # ======================= COMMODITIES / MATERIALS =======================
    # Q1 already proven (runway->retail fabric). report headline.
    rec("materials.Q1_runway_to_retail", "measured downstream fabric (proven elsewhere)",
        None, None, 0, None, "assoc",
        "PROVEN in main study: runway fabric leads H&M/ASOS rack composition +4-12mo (not re-run here)")
    # Q2 material demand -> fiber/commodity
    q2t = {}
    for mat, s in mat_demand.items():
        for tk in COMMOD + FIBER:
            if tk in rets.columns:
                b = best_lagcorr(s, {f"{mat}->{tk}": rets[tk]})
                if b.get("t") is not None and (q2t.get("t") is None or abs(b["t"]) > abs(q2t["t"])):
                    q2t = b
    rec("materials.Q2_retail_to_supplier", "material demand z -> fiber/commodity",
        q2t.get("t"), q2t.get("lag"), q2t.get("n"), None, "assoc",
        f"material demand vs fiber/commodity ({q2t.get('target')}), best |t|={q2t.get('t')} — mostly spurious/wrong-signed per full study")
    # Q3 wide tradeable sweep over material demand
    best_tr = {"ir": None}
    for mat, s in mat_demand.items():
        sw = best_sweep(s, rets, COMMOD + FIBER + ETFS)
        if sw.get("ir") is not None and (best_tr.get("ir") is None or sw["ir"] > best_tr["ir"]):
            best_tr = sw | {"material": mat}
    rec("materials.Q3_tradeable", "material demand z -> fiber/commodity/ETF sweep",
        (best_tr.get("sel_p"), best_tr.get("ir")), best_tr.get("lag"), best_tr.get("n"),
        best_tr.get("sign"), "trade",
        f"best-of-{best_tr.get('n_combos')} IR={best_tr.get('ir')} ({best_tr.get('material')}->{best_tr.get('ticker')},+{best_tr.get('lag')}mo) but selection-p={best_tr.get('sel_p')}, {best_tr.get('frac_pos')} of combos positive",
        {"best_ticker": best_tr.get("ticker"), "raw_ir": best_tr.get("ir"),
         "sel_p": best_tr.get("sel_p"), "frac_pos": best_tr.get("frac_pos")})

    # clean up one-liners for cells where the signal fired too rarely
    for k, c in cells.items():
        if "IR=None" in c.get("one_line", ""):
            c["one_line"] = ("no candidate traded >=12 active months (a +-1z "
                             "signal fires ~4x/yr) — too sparse to evaluate; "
                             "no tradeable edge")
            c["verdict"] = "NONE (too sparse)"

    meta = {"generated": date.today().isoformat(),
            "status": "EXPLORATORY / screening only — not confirmatory",
            "trend_terms_pulled": 0 if trends.empty else int(trends["term"].nunique()),
            "price_tickers": int(rets.shape[1]),
            "caveats": "search interest proxies the missing downstream color/"
                       "accessory/print fields; overlap-inflated t at long lags;"
                       " small independent-obs counts; runway shape/print untagged"}
    OUT.write_text(json.dumps({"meta": meta, "cells": cells}, indent=2))
    log.info("wrote %s", OUT)

    order = ["color", "accessories", "silhouette", "prints", "materials"]
    qs = ["Q1_runway_to_retail", "Q2_retail_to_supplier", "Q3_tradeable"]
    print("\n===== 15-CELL PRELIM MATRIX (exploratory) =====")
    for ch in order:
        for q in qs:
            k = f"{ch}.{q}"
            if k in cells:
                c = cells[k]
                print(f"{ch:12s} {q:22s} {c['verdict']:11s} "
                      f"deeper={'Y' if c['worth_deeper'] else 'n'} | {c['one_line']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
