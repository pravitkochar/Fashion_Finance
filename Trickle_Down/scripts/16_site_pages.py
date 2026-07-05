"""P8 (V2) — /historical and /predictions in the textile-editorial system.

Design system lives in 17_design_system.py (validated material palette,
fabric textures, loom hero, terminal slips). Data access reuses
09_dashboard's builders. Pages are content-only artifact files, no-JS safe
(the only JS is the loom tooltip enhancement), zero external requests.
Every honesty element is kept: TRENDS PROXY badges, no-frozen-model banner,
negative CV verdicts, coverage disclosure.

Outputs: dashboard/historical.html, dashboard/predictions.html
"""
from __future__ import annotations

import argparse
import importlib
import sys
from datetime import date

import pandas as pd

import lib_trickle as lt

m09 = importlib.import_module("09_dashboard")
ds = importlib.import_module("17_design_system")

log = lt.get_logger("16_site_pages")


def fmtn(x, d=2):
    try:
        return "—" if x is None else f"{float(x):.{d}f}"
    except (TypeError, ValueError):
        return str(x)


def pctn(x, d=1):
    try:
        return "—" if x is None else f"{100 * float(x):.{d}f}%"
    except (TypeError, ValueError):
        return str(x)


def spct(x, d=1):
    try:
        return f"{100 * float(x):+.{d}f}%"
    except (TypeError, ValueError):
        return "—"


# ------------------------------------------------------------ shared --------

def latest_season_shares():
    rmix = m09.safe_read(lt.DATA / "runway_mix.csv")
    if rmix is None:
        return "", [], pd.DataFrame()
    s = rmix[rmix["level"] == "season"].copy()
    if s.empty:
        return "", [], pd.DataFrame()
    latest = sorted(s["season_code"].unique(), key=lt.season_sort_key)[-1]
    cur = s[s["season_code"] == latest].dropna(subset=["share"])
    shares = sorted(((r["material"], float(r["share"]))
                     for _, r in cur.iterrows()), key=lambda t: -t[1])
    return latest, shares, cur.set_index("material")


def hop2_lags() -> dict:
    prop = m09.safe_read(lt.DATA / "propagation_train.csv")
    if prop is None:
        return {}
    h2 = prop[(prop["hop"] == 2) & prop["lag_months"].notna()]
    return {r["material"]: (int(r["lag_months"]), float(r["r"]))
            for _, r in h2.iterrows()}


def supplier_map() -> dict:
    out: dict = {}
    uni = lt.load_universe()
    for e in uni["tier3_suppliers"] + uni["commodities"]:
        for m in e.get("materials", []):
            out.setdefault(m, []).append(e["ticker"])
    return out


def build_loom() -> str:
    season, shares, _ = latest_season_shares()
    if not shares:
        return ds.empty("04_material_mix.py")
    lags, sups = hop2_lags(), supplier_map()
    threads = []
    for m, s in shares[:8]:
        if m == "other":
            continue
        lag = lags.get(m)
        threads.append({"material": m, "share": s,
                        "lag": lag[0] if lag else None,
                        "r": lag[1] if lag else None,
                        "suppliers": sups.get(m, [])})
    return ds.loom_svg(threads, season)


# --------------------------------------------------------- historical -------

def card_method() -> str:
    body = ('<p class="prose">Runway shows lead high-street material mixes, '
            "which lead the demand priced into fiber suppliers and "
            "commodities. This cascade is <b>measured, not assumed</b>: "
            "runway looks are vision-tagged per material; retailer mixes are "
            "reconstructed from Wayback-archived product pages, each row "
            "timestamped by its snapshot — no look-ahead; propagation is "
            "fitted on a 2017–2022 training window with walk-forward folds "
            "(validating 2020, 2021, 2022); 2023–2025 is a sealed test "
            "window, evaluated once with frozen parameters. Every "
            "methodology decision is pre-registered in DECISIONS.md before "
            "the run that uses it. Negative results are published with "
            "equal prominence.</p>")
    return ds.block("How this is measured", "", body)


def card_cv() -> str:
    cv = m09.safe_read(lt.REPORTS / "cv_results.csv")
    if cv is None:
        return ds.block("Cross-validation", "",
                        ds.empty("14_tune_signals.py"))
    summ = (cv.dropna(subset=["ir"]).groupby(["sleeve", "params", "source"])
            ["ir"].agg(["mean", "count"]).reset_index()
            .sort_values(["sleeve", "mean"], ascending=[True, False]))
    if summ.empty:
        return ds.block("Cross-validation", "",
                        '<div class="empty">No fold scores yet — sleeves '
                        "await measured data (H1) or deeper history.</div>")
    rows = [[r["sleeve"], r["params"], r["source"], fmtn(r["mean"], 3),
             int(r["count"])] for _, r in summ.iterrows()]
    best = summ["mean"].max()
    verdict = (f'<p class="callout">Best mean fold IR '
               f'<span class="num">{fmtn(best, 3)}</span> — '
               + ("clears zero; freeze pending review."
                  if best > 0 else
                  "does not clear zero, so no model is frozen and the "
                  "sealed test stays untouched. That is the discipline "
                  "working.") + "</p>")
    return ds.block("Cross-validation — every combination, every fold",
                    "A model is frozen only if mean fold IR clears zero; "
                    "the whole grid is shown, not just the winner.",
                    ds.slip_table(["sleeve", "params", "source",
                                   "mean fold IR", "folds"], rows,
                                  signed_cols={3}) + verdict)


def card_backtest() -> str:
    bt = m09.build_backtest()
    if not bt:
        return ds.block("Backtest", "", ds.empty("08_backtest.py"))
    f = bt.get("findings", {})
    meta = f.get("meta", {})
    primary = f.get("h2", {}).get("nowcast_trends_monthly", {})
    parts = []
    if "sharpe" in primary:
        tiles = [("Sharpe", fmtn(primary.get("sharpe"))),
                 ("IR vs XRT", fmtn(primary.get("ir"))),
                 ("Hit rate", pctn(primary.get("hit_rate"))),
                 ("CAR", pctn(primary.get("car"))),
                 ("Max drawdown", pctn(primary.get("max_drawdown"))),
                 ("Rebalances", str(primary.get("n_rebalances")))]
        parts.append(ds.slip_table([t[0] for t in tiles],
                                   [[t[1] for t in tiles]],
                                   signed_cols={0, 1, 3, 4}))
    rows = []
    for root in ("h1", "h2"):
        for key, m in f.get(root, {}).items():
            if key == "reference_commodities_car" or not isinstance(m, dict):
                continue
            rows.append([f"{root}_{key}", fmtn(m.get("sharpe")),
                         pctn(m.get("car")), pctn(m.get("max_drawdown")),
                         m.get("status", "ok")])
    if rows:
        parts.append(ds.slip_table(["run", "sharpe", "CAR", "maxDD",
                                    "status"], rows, signed_cols={1, 2, 3}))
    ref = f.get("h2", {}).get("reference_commodities_car")
    if ref:
        parts.append('<p class="footnote">Commodity reference CAR (never '
                     "P&amp;L): " + ", ".join(f"{k} {pctn(v)}"
                                              for k, v in ref.items())
                     + "</p>")
    if meta:
        parts.append(f'<p class="footnote">Window {meta.get("dev_window")} · '
                     f'{meta.get("cost_bps_per_side")} bps/side · turnover '
                     f'cap {meta.get("turnover_cap_oneway")} · run '
                     f'{meta.get("run_date")}</p>')
    return ds.block("Backtest — pre-registered runs",
                    "All runs reported (objectivity charter); dev window "
                    "only, the holdout stays sealed.",
                    "".join(parts), badge="trends proxy")


def card_coverage() -> str:
    cov = m09.safe_read(lt.DATA / "wayback_coverage.csv")
    if cov is None:
        return ds.block("Measured-history coverage", "",
                        ds.empty("11_wayback_downstream.py"))
    g = (cov.groupby("retailer")
         .agg(months=("month", "nunique"), first=("month", "min"),
              last=("month", "max"), comp=("n_comp", "sum"),
              ok=("n_comp", lambda s: int((s >= 30).sum())))
         .reset_index())
    return ds.block("Measured-history coverage",
                    "Wayback-reconstructed retailer months; the signal "
                    "floor is 30 parsed compositions per month.",
                    ds.slip_table(["retailer", "months", "first", "last",
                                   "compositions", "months ≥30"],
                                  g.values.tolist()))


def card_propagation() -> str:
    p = m09.build_propagation()
    if not p or not p.get("fitted_train"):
        return ds.block("Fitted propagation", "",
                        ds.empty("13_fit_propagation.py"))
    hop_names = {1: "runway→retail", 2: "runway→trends", 3: "retail→payoff"}
    rows = [[hop_names.get(r["hop"], r["hop"]), r["retailer"], r["material"],
             f"+{int(r['lag_months'])}mo", fmtn(r.get("r")),
             fmtn(r.get("adoption_coef")), r.get("n_obs")]
            for r in p["fitted_train"]]
    return ds.block("Fitted propagation — the cascade, measured",
                    "Lagged cross-correlation on the 2017–2022 train window "
                    "only. Hops 1 and 3 populate as archive coverage lands.",
                    ds.slip_table(["hop", "entity", "material", "lag", "r",
                                   "coef", "n"], rows, signed_cols={4, 5}))


def build_historical() -> str:
    season, _, _ = latest_season_shares()
    hero = ds.block(f"The cascade — {season or 'awaiting data'}",
                    "Thread width = share of the season's tagged looks; the "
                    "drop to high street lands at each material's fitted "
                    "lag; threads reaching the mills name their suppliers. "
                    "Faded stubs have no fitted lag yet.",
                    build_loom())
    heat = ds.block("Eleven years of runway fabric",
                    "Season-level share of each material across tagged "
                    "looks; deeper dye = larger share.",
                    ds.heatmap(m09.build_runway_heatmap()))
    return ds.page("Historical", "Historical", date.today().isoformat(),
                   [hero, card_method(), heat, card_propagation(),
                    card_cv(), card_backtest(), card_coverage()])


# -------------------------------------------------------- predictions -------

def season_spread() -> str:
    season, shares, cur = latest_season_shares()
    if not shares:
        return ds.empty("04_material_mix.py")
    pretty = f"{season[:2]} {season[2:]}"
    emergent = [(m, r) for m, r in cur.iterrows()
                if str(r.get("is_emergent")) == "True"]
    callouts = []
    for m, r in sorted(emergent, key=lambda t: -float(
            t[1].get("delta_vs_trail3") or 0))[:2]:
        callouts.append(
            f'<p class="callout"><b>{ds.esc(str(m)).title()}</b> is having '
            f'a moment — <span class="num">{pctn(r["share"])}</span> of '
            f'{ds.esc(season)} looks, <span class="num">'
            f'{spct(r.get("delta_vs_trail3"))}</span> versus its trailing '
            'three seasons. <span class="emergent">EMERGENT</span></p>')
    chips = " &nbsp; ".join(ds.chip(m) for m, s in shares[:8]
                            if m != "other")
    return ('<section class="block">'
            f'<div style="font:italic 400 92px/1 var(--serif);'
            f'margin:26px 0 6px">{ds.esc(pretty)}</div>'
            '<p class="note">The season&#x27;s cloth, as tagged from the '
            "runway.</p>" + ds.palette_strip(shares)
            + f'<div style="margin:10px 0 6px">{chips}</div>'
            + "".join(callouts) + "</section>")


def card_status() -> str:
    if (lt.CONFIG / "model_v2.json").exists():
        return ds.block("Model status", "",
                        '<p class="prose">Parameters are CV-frozen '
                        "(config/model_v2.json); the views below use "
                        "them.</p>")
    return ds.block("Model status", "",
                    '<p class="prose"><b>No frozen model yet.</b> '
                    "Everything below is the pre-registered machinery "
                    "running on accumulating data — directional context, "
                    "not tradeable advice. It graduates when "
                    "cross-validation clears zero and the model freezes."
                    "</p>", badge="pre-freeze")


def card_implied() -> str:
    prop = m09.safe_read(lt.DATA / "propagation_train.csv")
    season, shares, cur = latest_season_shares()
    if prop is None or cur.empty:
        return ds.block("Implied demand path", "",
                        ds.empty("13_fit_propagation.py"))
    hop2 = prop[(prop["hop"] == 2) & prop["lag_months"].notna()]
    rows = []
    for _, r in hop2.sort_values("r", ascending=False).iterrows():
        m = r["material"]
        if m not in cur.index:
            continue
        delta = cur.loc[m].get("delta_vs_trail3")
        if pd.isna(delta):
            continue
        eta = (pd.Timestamp(lt.season_known_date(season))
               + pd.DateOffset(months=int(r["lag_months"])))
        rows.append([m, spct(delta), f"+{int(r['lag_months'])}mo",
                     fmtn(r["r"]), eta.strftime("%Y-%m"),
                     "interest rising" if float(delta) > 0
                     else "interest fading"])
    if not rows:
        return ds.block("Implied demand path", "",
                        ds.empty("13_fit_propagation.py"))
    return ds.block("Implied demand path",
                    f"Runway shifts in {season} propagate to consumer "
                    "interest at each material's fitted lag.",
                    ds.slip_table(["material", f"runway Δ ({season})",
                                   "lag", "r", "impact window", "read"],
                                  rows, signed_cols={1}))


def card_supplier_read() -> str:
    nc = m09.safe_read(lt.DATA / "signals_nowcast_trends.csv")
    if nc is None:
        return ds.block("Supplier / commodity read", "",
                        ds.empty("07_signals.py"))
    latest = nc["date"].max()
    cur = (nc[nc["date"] == latest].dropna(subset=["nowcast_z"])
           .sort_values("nowcast_z", ascending=False))
    rows = [[r["material"], fmtn(r["nowcast_z"]), r["direction"],
             r["tickers"]] for _, r in cur.iterrows()]
    return ds.block(f"Supplier / commodity read — {latest}",
                    "z-score of proxy demand vs its trailing year; |z|>1 "
                    "gates long/short on mapped names. Commodities are "
                    "references, never P&L.",
                    ds.slip_table(["material", "z", "direction",
                                   "mapped names"], rows, signed_cols={1}),
                    badge="trends proxy")


def build_predictions() -> str:
    return ds.page("Predictions", "Predictions", date.today().isoformat(),
                   [season_spread(), card_status(), card_implied(),
                    card_supplier_read()])


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    lt.ensure_dirs()
    for name, html in (("historical.html", build_historical()),
                       ("predictions.html", build_predictions())):
        out = lt.DASHBOARD / name
        out.write_text(html, encoding="utf-8")
        log.info("%s written (%d bytes)", out, len(html))
    return 0


if __name__ == "__main__":
    sys.exit(main())
