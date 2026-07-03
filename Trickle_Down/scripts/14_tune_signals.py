"""P5 (V2) — walk-forward CV over the pre-registered grid; freeze the model.

Folds (locked): validate 2020, 2021, 2022 — parameters constant per combo,
signals built point-in-time (PITStore), portfolio evaluated on the fold's
validation year only. Selection = mean fold IR vs XRT, tie-break lower
turnover proxy (n_rebalances-weighted gross moves).

Grid actually exercised (subset of the registered grid; dims not yet
implementable are FIXED at defaults and disclosed at freeze time — additions
beyond the registered grid are forbidden):
  H2: z_gate {0.5, 1.0, 1.5} x trail {9, 12, 18}
  H1: leg_div {3, 5} x window {6, 9, 12} x min_materials {5, 6, 8}
  fixed: n_items floor = 30 (04's thin_sample), lag = fitted (hop timing is
  structural in the H1 construction).

Outputs: reports/cv_results.csv (EVERY combo x fold — nothing hidden)
         --freeze: config/model_v2.json + a DECISIONS-ready block on stdout
                   (appending to DECISIONS.md stays a human/manual act).

H2 source: measured downstream mix when present, else the labeled trends
proxy (v1 addendum) — recorded in every output row.
"""
from __future__ import annotations

import argparse
import importlib
import itertools
import json
import sys
from datetime import date

import pandas as pd

import lib_trickle as lt
import lib_xsec as lx

m07 = importlib.import_module("07_signals")
m08 = importlib.import_module("08_backtest")

log = lt.get_logger("14_tune")

FOLDS = [  # (name, val_start, val_end)
    ("fold1_2020", "2020-01-01", "2020-12-31"),
    ("fold2_2021", "2021-01-01", "2021-12-31"),
    ("fold3_2022", "2022-01-01", "2022-12-31"),
]
H2_GRID = list(itertools.product((0.5, 1.0, 1.5), (9, 12, 18)))
H1_GRID = list(itertools.product((3, 5), (6, 9, 12), (5, 6, 8)))
COST_BPS, CAP = 20.0, 0.5


def market_data():
    uni = m08.universe_pieces()
    returns = lx.load_prices(m08.PRICES_PATH)
    tradeable = set(returns.columns)
    bench_wide = returns[[b for b in uni["benches"] if b in tradeable]]
    bench = returns[uni["etf"]] if uni["etf"] in tradeable else None
    t2 = [t for t in uni["tier2"] if t in tradeable]
    t3 = [t for t in uni["tier3"] if t in tradeable]
    ex2 = lx.excess_returns(returns[t2],
                            {t: r.get("bench") for t, r in uni["tier2"].items()},
                            bench_wide)
    ex3 = lx.excess_returns(returns[t3],
                            {t: s.get("bench") for t, s in uni["tier3"].items()},
                            bench_wide) if t3 else pd.DataFrame()
    return uni, tradeable, bench, ex2, ex3


def fold_ir(weights: dict, excess: pd.DataFrame, bench: pd.Series,
            start: str, end: str, ppy: int) -> float | None:
    clipped = {t: w for t, w in weights.items()
               if pd.Timestamp(start) <= t <= pd.Timestamp(end)}
    if len(clipped) < 2:
        return None
    window = excess.loc[excess.index <= pd.Timestamp(end)]
    port, _ = lx.portfolio_path(clipped, window, COST_BPS)
    port = port.loc[str(start):str(end)]
    if port.empty:
        return None
    m = lx.metrics(port, bench, ppy)
    return m.get("ir")


def run_h2(store, z_gate: float, trail: int, end: str) -> pd.DataFrame:
    m07.Z_GATE, m07.NOWCAST_TRAIL = z_gate, trail
    return m07.build_h2(store, m07.monthly_dates(date(2016, 7, 1),
                                                 date.fromisoformat(end)))


def run_h1(store, leg_div: int, window: int, min_mats: int,
           end: str, retailer_ticker: dict) -> pd.DataFrame:
    m07.LEG_DIV, m07.WINDOW_MONTHS, m07.MIN_MATERIALS = \
        leg_div, window, min_mats
    return m07.build_h1(store, "monthly",
                        m07.monthly_dates(date(2016, 7, 1),
                                          date.fromisoformat(end)),
                        retailer_ticker)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freeze", action="store_true",
                    help="write config/model_v2.json from the winners")
    args = ap.parse_args()
    lt.ensure_dirs()

    if not m08.PRICES_PATH.exists():
        log.error("prices missing — run 08_backtest.py --fetch first")
        return 1
    uni, tradeable, bench, ex2, ex3 = market_data()
    t3_tradeable = tradeable & set(uni["tier3"])

    measured = m07.load_store()
    trends = m07.load_trends_store()
    # measured wins only when it has enough months to produce a nowcast at
    # the largest trailing window in the grid; else the labeled proxy
    deep_enough = False
    if measured is not None:
        dm = measured.downstream_asof(FOLDS[-1][2])
        deep_enough = (not dm.empty
                       and dm["month"].nunique() >= max(t for _, t in H2_GRID) + 1)
    h2_store, h2_src = ((measured, "measured") if deep_enough
                        else (trends, "trends_proxy"))
    log.info("H2 tuning source: %s", h2_src)
    rows = []

    # ---- H2 grid ---------------------------------------------------------
    if h2_store is None or ex3.empty:
        log.warning("H2 tuning skipped: no store / no supplier prices")
    else:
        for z_gate, trail in H2_GRID:
            for fname, vs, ve in FOLDS:
                sig = run_h2(h2_store, z_gate, trail, ve)
                ir = None
                if not sig.empty:
                    w = m08.h2_weights(sig, CAP, t3_tradeable)
                    ir = fold_ir(w, ex3, bench, vs, ve, 12)
                rows.append({"sleeve": "h2", "params": f"z={z_gate},trail={trail}",
                             "fold": fname, "ir": ir, "source": h2_src})
            log.info("H2 z=%s trail=%s done", z_gate, trail)

    # ---- H1 grid ---------------------------------------------------------
    retailer_ticker = {r["key"]: r["ticker"]
                       for r in lt.load_universe()["tier2_retailers"]
                       if r["ticker"]}
    if measured is None:
        log.warning("H1 tuning skipped: measured downstream mix not yet "
                    "available (wayback sweep still accumulating)")
    else:
        for leg_div, window, min_mats in H1_GRID:
            for fname, vs, ve in FOLDS:
                sig = run_h1(measured, leg_div, window, min_mats, ve,
                             retailer_ticker)
                ir = None
                if not sig.empty:
                    w = m08.h1_weights(sig, "monthly", CAP, tradeable)
                    ir = fold_ir(w, ex2, bench, vs, ve, 12)
                rows.append({"sleeve": "h1",
                             "params": f"leg={leg_div},win={window},"
                                       f"mats={min_mats}",
                             "fold": fname, "ir": ir, "source": "measured"})
            log.info("H1 leg=%s win=%s mats=%s done", leg_div, window, min_mats)

    if not rows:
        log.error("nothing tuned — no data available for either sleeve")
        return 1
    cv = pd.DataFrame(rows)
    cv.to_csv(lt.REPORTS / "cv_results.csv", index=False)

    summary = (cv.dropna(subset=["ir"])
               .groupby(["sleeve", "params"])["ir"]
               .agg(["mean", "count"]).reset_index()
               .sort_values(["sleeve", "mean"], ascending=[True, False]))
    log.info("CV summary (mean fold IR):\n%s", summary.to_string(index=False))

    if args.freeze:
        cfg = {"frozen": date.today().isoformat(), "h2_source": h2_src,
               "selection": "mean fold IR vs XRT (DECISIONS.md V2 entry)"}
        for sleeve, keymap in (("h2", {"z": "z_gate", "trail": "nowcast_trail"}),
                               ("h1", {"leg": "leg_div", "win": "window_months",
                                       "mats": "min_materials"})):
            top = summary[summary["sleeve"] == sleeve]
            if top.empty:
                continue
            best = top.iloc[0]
            for part in best["params"].split(","):
                k, v = part.split("=")
                cfg[keymap[k]] = float(v) if "." in v else int(v)
            cfg[f"{sleeve}_mean_fold_ir"] = round(float(best["mean"]), 4)
        m07.MODEL_CONFIG.write_text(json.dumps(cfg, indent=2))
        log.info("config/model_v2.json written: %s", cfg)
        log.info("NEXT (manual, per charter): append a 'MODEL V2 FROZEN' "
                 "entry to DECISIONS.md quoting this config, then 08 "
                 "--window test unlocks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
