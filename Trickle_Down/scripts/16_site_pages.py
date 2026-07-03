"""P8 (V2, scaffold) — generate the /historical and /predictions site pages.

Static, artifact-ready HTML (content-only: title + styles + body), reusing
09_dashboard's builders and static renderers so all three pages share one
design system. Both pages render honestly TODAY and auto-fill as the
wayback sweep / tag backfill / tuning land — every section states its data
basis (measured vs proxy, frozen vs unfrozen).

Outputs: dashboard/historical.html, dashboard/predictions.html
"""
from __future__ import annotations

import argparse
import importlib
import re
import sys
from datetime import date

import pandas as pd

import lib_trickle as lt

m09 = importlib.import_module("09_dashboard")
log = lt.get_logger("16_site_pages")

STYLES = "\n".join(re.findall(r"<style>.*?</style>", m09.TEMPLATE, re.S))
NAV = ('<p class="meta">Trickle Down — <b>{here}</b> · '
       'pages: Historical / Predictions / Live dashboard</p>')


def page(title: str, here: str, body_cards: list[str]) -> str:
    cards = "".join(f'<section class="card">{c}</section>' for c in body_cards)
    return (f"<title>Trickle Down — {title}</title>\n{STYLES}\n"
            f'<div class="wrap"><header><h1>Trickle Down — {title}</h1>'
            + NAV.format(here=here)
            + f'<p class="meta">Generated {date.today().isoformat()} · '
            'rebuilt daily · all results net of costs, point-in-time</p>'
            f'</header><div class="grid">{cards}</div></div>')


# ------------------------------------------------------------ historical ----

def card_method() -> str:
    return (m09.s_header("Method", "") +
            "<p>Runway shows lead high-street material mixes, which lead "
            "material demand priced into fiber suppliers and commodities. "
            "The cascade is <b>measured, not assumed</b>: runway looks are "
            "vision-tagged per material; retailer mixes are reconstructed "
            "from Wayback-archived product pages (each row timestamped by "
            "its snapshot — no look-ahead); propagation is fitted on a "
            "2017–2022 training window with walk-forward folds (validate "
            "2020/21/22); 2023–2025 is a sealed test window evaluated once "
            "with frozen parameters. Every methodology decision is "
            "pre-registered in DECISIONS.md before the run that uses it. "
            "Negative results are published with equal prominence.</p>")


def card_cv() -> str:
    head = m09.s_header("Cross-validation results",
                        "Every grid combination × fold — nothing hidden. "
                        "A model is frozen only if mean fold IR clears zero.")
    cv = m09.safe_read(lt.REPORTS / "cv_results.csv")
    if cv is None:
        return head + m09.s_empty("14_tune_signals.py")
    summ = (cv.dropna(subset=["ir"]).groupby(["sleeve", "params", "source"])
            ["ir"].agg(["mean", "count"]).reset_index()
            .sort_values(["sleeve", "mean"], ascending=[True, False]))
    if summ.empty:
        return head + ('<div class="empty">No fold scores yet — sleeves '
                       "await measured data (H1) or deeper history.</div>")
    rows = [[r["sleeve"], r["params"], r["source"],
             m09.fmtn(r["mean"], 3), int(r["count"])]
            for _, r in summ.iterrows()]
    verdict = ("<p class='footnote'>Best mean fold IR: "
               f"{m09.fmtn(summ['mean'].max(), 3)} — "
               + ("clears zero; freeze pending review."
                  if summ["mean"].max() > 0 else
                  "does not clear zero → NOT frozen, sealed test not "
                  "earned (DECISIONS.md).") + "</p>")
    return head + m09.s_table(["sleeve", "params", "source",
                               "mean fold IR", "folds"], rows) + verdict


def card_coverage() -> str:
    head = m09.s_header("Measured-history coverage",
                        "Wayback-reconstructed retailer months (composition "
                        "count per month; signal floor is 30).")
    cov = m09.safe_read(lt.DATA / "wayback_coverage.csv")
    if cov is None:
        return head + m09.s_empty("11_wayback_downstream.py")
    g = (cov.groupby("retailer")
         .agg(months=("month", "nunique"), first=("month", "min"),
              last=("month", "max"), comp_total=("n_comp", "sum"),
              months_ok=("n_comp", lambda s: int((s >= 30).sum())))
         .reset_index())
    rows = g.values.tolist()
    return head + m09.s_table(
        ["retailer", "months sampled", "first", "last", "compositions",
         "months ≥30"], rows)


def build_historical() -> str:
    cards = [
        card_method(),
        m09.static_heatmap(m09.build_runway_heatmap()),
        m09.static_propagation(m09.build_propagation()),
        card_cv(),
        m09.static_backtest(m09.build_backtest()),
        card_coverage(),
    ]
    return page("Historical", "Historical", cards)


# ----------------------------------------------------------- predictions ----

def card_status_banner() -> str:
    frozen = (lt.CONFIG / "model_v2.json").exists()
    if frozen:
        return (m09.s_header("Model status", "") +
                "<p>Parameters are CV-frozen (config/model_v2.json); the "
                "views below use them.</p>")
    return (m09.s_header("Model status", "") +
            "<p><b>No frozen model yet.</b> Everything below is the "
            "pre-registered machinery running on accumulating data — "
            "directional context, not tradeable advice. It graduates when "
            "cross-validation clears zero and the model freezes.</p>")


def card_emergent() -> str:
    head = m09.s_header("Latest runway season — emergent materials",
                        "Share vs trailing-3-season mean; the leading edge "
                        "of the cascade.")
    rmix = m09.safe_read(lt.DATA / "runway_mix.csv")
    if rmix is None:
        return head + m09.s_empty("04_material_mix.py")
    s = rmix[rmix["level"] == "season"].copy()
    if s.empty or "delta_vs_trail3" not in s.columns:
        return head + m09.s_empty("04_material_mix.py")
    latest = sorted(s["season_code"].unique(), key=lt.season_sort_key)[-1]
    cur = (s[s["season_code"] == latest]
           .sort_values("delta_vs_trail3", ascending=False))
    rows = [[r["material"], m09.pctn(r["share"]),
             m09.pctn(r.get("delta_vs_trail3")),
             "EMERGENT" if r.get("is_emergent") in (True, "True") else ""]
            for _, r in cur.iterrows() if pd.notna(r.get("share"))]
    return (m09.s_header(f"Latest runway season: {latest}",
                         "Share vs trailing-3-season mean.")
            + m09.s_table(["material", "share", "Δ vs trail-3", ""], rows))


def card_implied_path() -> str:
    head = m09.s_header("Implied demand path (fitted lags)",
                        "Runway shifts propagate to consumer interest at "
                        "the train-fitted lag per material.")
    prop = m09.safe_read(lt.DATA / "propagation_train.csv")
    rmix = m09.safe_read(lt.DATA / "runway_mix.csv")
    if prop is None or rmix is None:
        return head + m09.s_empty("13_fit_propagation.py")
    hop2 = prop[(prop["hop"] == 2) & prop["lag_months"].notna()]
    s = rmix[rmix["level"] == "season"]
    latest = sorted(s["season_code"].unique(), key=lt.season_sort_key)[-1]
    cur = s[s["season_code"] == latest].set_index("material")
    rows = []
    for _, r in hop2.sort_values("r", ascending=False).iterrows():
        mat = r["material"]
        delta = cur["delta_vs_trail3"].get(mat)
        if pd.isna(delta):
            continue
        known = lt.season_known_date(latest)
        eta = (pd.Timestamp(known)
               + pd.DateOffset(months=int(r["lag_months"])))
        rows.append([mat, m09.pctn(delta),
                     f"+{int(r['lag_months'])}mo (r={m09.fmtn(r['r'])})",
                     eta.strftime("%Y-%m"),
                     "rising interest expected" if delta > 0
                     else "fading interest expected"])
    if not rows:
        return head + m09.s_empty("13_fit_propagation.py")
    return head + m09.s_table(
        ["material", f"runway Δ ({latest})", "fitted lag", "impact window",
         "read"], rows)


def card_positioning() -> str:
    head = m09.s_header("Supplier / commodity read (proxy nowcast)",
                        "Current trends-proxy z-scores mapped to Tier-3 "
                        "names; commodities are references, never P&L.")
    nc = m09.safe_read(lt.DATA / "signals_nowcast_trends.csv")
    if nc is None:
        return head + m09.s_empty("07_signals.py")
    latest = nc["date"].max()
    cur = (nc[nc["date"] == latest]
           .sort_values("nowcast_z", ascending=False))
    rows = [[r["material"], m09.fmtn(r["nowcast_z"]), r["direction"],
             r["tickers"]] for _, r in cur.iterrows()
            if pd.notna(r["nowcast_z"])]
    return (m09.s_header(f"Supplier / commodity read — {latest}",
                         "TRENDS PROXY (v1 addendum), pre-freeze.")
            + m09.s_table(["material", "z", "direction", "mapped names"],
                          rows))


def build_predictions() -> str:
    cards = [card_status_banner(), card_emergent(), card_implied_path(),
             card_positioning()]
    return page("Predictions", "Predictions", cards)


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
