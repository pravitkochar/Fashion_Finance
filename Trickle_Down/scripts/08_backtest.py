"""P4/P5 — run the pre-registered backtests (H1 adoption factor, H2 nowcast).

Reads data/signals_adoption.csv + data/signals_nowcast.csv, prices from
data/prices/prices_tier23.csv (--fetch to download/refresh via yfinance).

Reports ALL pre-registered runs — seasonal primary, monthly robustness, H2
sleeve — net of costs, per the objectivity charter. Dev window default
2016-01-01..2023-12-31; --include-holdout unlocks 2024-2025 and logs a loud
warning citing the DECISIONS.md holdout rule.

Outputs:
    reports/findings.json           all runs, all metrics, meta
    reports/backtest_summary.md     human-readable
    reports/backtest_results.csv    per-rebalance-period returns
    reports/equity_curves.csv       daily equity per strategy (dashboard)
    reports/img/bt_*.png            equity + drawdown charts
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import lib_trickle as lt
import lib_xsec as lx

log = lt.get_logger("08_backtest")

DEV_START, DEV_END = "2016-01-01", "2023-12-31"
HOLDOUT_START, HOLDOUT_END = "2024-01-01", "2025-12-31"
PRICES_PATH = lt.PRICES / "prices_tier23.csv"


# ------------------------------------------------------------ universe ------

def universe_pieces() -> dict:
    uni = lt.load_universe()
    tier2 = {r["ticker"]: r for r in uni["tier2_retailers"] if r["ticker"]}
    tier3 = {s["ticker"]: s for s in uni["tier3_suppliers"]}
    commodities = [c["ticker"] for c in uni["commodities"]]
    benches = sorted({e.get("bench") for e in
                      list(tier2.values()) + list(tier3.values()) if e.get("bench")})
    return {
        "tier2": tier2, "tier3": tier3, "commodities": commodities,
        "benches": benches, "etf": uni["benchmark_etf"],
        "all_tickers": (list(tier2) + list(tier3) + commodities
                        + benches + [uni["benchmark_etf"]]),
    }


def universe_hash() -> str:
    return hashlib.sha1((lt.CONFIG / "universe.json").read_bytes()).hexdigest()[:12]


# ------------------------------------------------------------- weights ------

def h1_weights(signals: pd.DataFrame, cadence: str, cap: float,
               tradeable: set) -> dict:
    """signals_adoption rows -> {timestamp: capped weight Series}."""
    sub = signals[signals["cadence"] == cadence].copy()
    if sub.empty:
        return {}
    sub["rebalance_date"] = pd.to_datetime(sub["rebalance_date"])
    out, prev = {}, pd.Series(dtype=float)
    for reb, grp in sub.groupby("rebalance_date"):
        target = grp.set_index("ticker")["weight"].astype(float)
        dropped = [t for t in target.index if t not in tradeable]
        if dropped:
            log.warning("%s %s: dropping %s (no price data); weights NOT "
                        "renormalized — exposure shrinks, disclosed not hidden",
                        cadence, reb.date(), dropped)
            target = target.drop(dropped)
        capped = lx.apply_turnover_cap(prev, target, cap)
        out[reb] = capped
        prev = capped
    return out


def h2_weights(nowcast: pd.DataFrame, cap: float, tradeable: set) -> dict:
    """signals_nowcast rows -> equal-weight supplier positions per month."""
    nowcast = nowcast.copy()
    nowcast["date"] = pd.to_datetime(nowcast["date"])
    out, prev = {}, pd.Series(dtype=float)
    for reb, grp in nowcast.groupby("date"):
        legs: dict[str, float] = {}
        for _, row in grp.iterrows():
            if row["direction"] not in ("long", "short"):
                continue
            sign = 1.0 if row["direction"] == "long" else -1.0
            for ticker in str(row["tickers"]).split(";"):
                ticker = ticker.strip()
                if ticker and ticker in tradeable:
                    legs[ticker] = legs.get(ticker, 0.0) + sign
        target = pd.Series(legs, dtype=float)
        if not target.empty and target.abs().sum() > 0:
            target = target / target.abs().sum()      # gross = 1
        capped = lx.apply_turnover_cap(prev, target, cap)
        out[reb] = capped
        prev = capped
    return out


# ------------------------------------------------------------ strategy ------

def clip_weights(weights: dict, start: str, end: str) -> dict:
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    return {t: w for t, w in weights.items() if lo <= t <= hi}


def run_strategy(name: str, weights: dict, excess_wide: pd.DataFrame,
                 bench_daily: pd.Series, start: str, end: str,
                 cost_bps: float, ppy: int) -> tuple[dict, pd.Series, list]:
    weights = clip_weights(weights, start, end)
    if len(weights) < 3:
        log.warning("%s: <3 rebalances in %s..%s — skipped", name, start, end)
        return {"status": "insufficient_rebalances",
                "n_rebalances": len(weights)}, pd.Series(dtype=float), []
    window_rets = excess_wide.loc[excess_wide.index <= pd.Timestamp(end)]
    port, equity = lx.portfolio_path(weights, window_rets, cost_bps)
    if port.empty:
        return {"status": "no_return_data"}, pd.Series(dtype=float), []
    reb_dates = sorted(weights)
    period_rows, period_vals = [], []
    for i, t0 in enumerate(reb_dates):
        t1 = reb_dates[i + 1] if i + 1 < len(reb_dates) else pd.Timestamp(end)
        chunk = port[(port.index > t0) & (port.index <= t1)]
        if chunk.empty:
            continue
        ret = float((1 + chunk).prod() - 1)
        period_vals.append(ret)
        period_rows.append({"strategy": name, "period_start": t0.date(),
                            "period_end": t1.date(), "port_ret": round(ret, 6)})
    m = lx.metrics(port, bench_daily, ppy,
                   period_rets=pd.Series(period_vals, dtype=float))
    m["n_rebalances"] = len(weights)
    log.info("%s: %s", name, m)
    return m, equity, period_rows


def save_chart(name: str, equity: pd.Series) -> None:
    if equity.empty:
        return
    dd = equity / equity.cummax() - 1
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(equity.index, equity.values, lw=1.4)
    ax1.set_title(f"{name} — equity (net of costs)")
    ax1.grid(alpha=0.3)
    ax2.fill_between(dd.index, dd.values, 0, alpha=0.5)
    ax2.set_title("drawdown")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    out = lt.REPORTS / "img" / f"bt_{name}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    log.info("chart -> %s", out)


# ---------------------------------------------------------------- main ------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true",
                    help="download/refresh Tier2/3 + bench prices first")
    ap.add_argument("--start", default=DEV_START)
    ap.add_argument("--end", default=DEV_END)
    ap.add_argument("--window", choices=["dev", "test"], default="dev",
                    help="test = sealed 2023-2025 window (needs frozen model)")
    ap.add_argument("--include-holdout", action="store_true")
    ap.add_argument("--cost-bps", type=float, default=20.0)
    ap.add_argument("--turnover-cap", type=float, default=0.5)
    args = ap.parse_args()

    if args.window == "test":
        # The seal (PLAN_V2/DECISIONS): the test window may only be touched
        # once, with CV-frozen parameters on the record.
        decisions = (lt.ROOT / "DECISIONS.md").read_text(encoding="utf-8") \
            if (lt.ROOT / "DECISIONS.md").exists() else ""
        frozen_cfg = lt.CONFIG / "model_v2.json"
        if "MODEL V2 FROZEN" not in decisions or not frozen_cfg.exists():
            log.error("TEST WINDOW SEALED: requires config/model_v2.json AND "
                      "a 'MODEL V2 FROZEN' entry in DECISIONS.md (run "
                      "14_tune_signals.py --freeze, log the entry, retry).")
            return 2
        args.start, args.end = "2023-01-01", "2025-12-31"
        log.warning("SEALED TEST WINDOW UNLOCKED (%s..%s) — one evaluation, "
                    "reported as-is per the objectivity charter.",
                    args.start, args.end)

    lt.ensure_dirs()
    uni = universe_pieces()

    if args.fetch:
        lx.fetch_prices(uni["all_tickers"], "2014-01-01",
                        date.today().isoformat(), PRICES_PATH)
    if not PRICES_PATH.exists():
        log.error("no price file at %s — run with --fetch first", PRICES_PATH)
        return 1

    sig_path = lt.DATA / "signals_adoption.csv"
    if not sig_path.exists() or pd.read_csv(sig_path).empty:
        log.warning("signals_adoption.csv missing/empty — H1 is forward-only "
                    "in v1 (DECISIONS.md addendum); running H2 sleeves only")
        signals = pd.DataFrame(columns=["rebalance_date", "ticker", "score",
                                        "rank", "weight", "cadence"])
    else:
        signals = pd.read_csv(sig_path)

    returns_wide = lx.load_prices(PRICES_PATH)
    tradeable = set(returns_wide.columns)
    bench_wide = returns_wide[[b for b in uni["benches"] if b in tradeable]]
    etf = uni["etf"]
    bench_daily = returns_wide[etf] if etf in tradeable else None
    if bench_daily is None:
        log.warning("benchmark ETF %s missing from prices — IR will be null", etf)

    t2_map = {t: r.get("bench") for t, r in uni["tier2"].items()}
    t3_map = {t: s.get("bench") for t, s in uni["tier3"].items()}
    t2_cols = [t for t in uni["tier2"] if t in tradeable]
    t3_cols = [t for t in uni["tier3"] if t in tradeable]
    excess_t2 = lx.excess_returns(returns_wide[t2_cols], t2_map, bench_wide)
    excess_t3 = (lx.excess_returns(returns_wide[t3_cols], t3_map, bench_wide)
                 if t3_cols else pd.DataFrame())

    findings: dict = {"h1": {}, "h2": {}, "meta": {}}
    equity_rows, period_rows = [], []

    def record(key_root: str, key: str, weights: dict,
               excess: pd.DataFrame, start: str, end: str, ppy: int) -> None:
        m, equity, rows = run_strategy(f"{key_root}_{key}", weights, excess,
                                       bench_daily, start, end,
                                       args.cost_bps, ppy)
        findings[key_root][key] = m
        period_rows.extend(rows)
        for ts, val in equity.items():
            equity_rows.append({"strategy": f"{key_root}_{key}",
                                "date": ts.date(), "equity": round(val, 6)})
        save_chart(f"{key_root}_{key}", equity)

    # ---- H1: adoption-speed factor -------------------------------------
    for cadence, ppy in (("seasonal", 2), ("monthly", 12)):
        weights = h1_weights(signals, cadence, args.turnover_cap, tradeable)
        if not weights:
            findings["h1"][cadence] = {"status": "no_signals"}
            continue
        record("h1", cadence, weights, excess_t2, args.start, args.end, ppy)
        if args.include_holdout:
            log.warning("HOLDOUT UNLOCKED (%s..%s) — per DECISIONS.md this is "
                        "only valid if the dev-window methodology was frozen "
                        "in a DECISIONS.md entry FIRST. Results are keyed "
                        "separately and must be reported as holdout.",
                        HOLDOUT_START, HOLDOUT_END)
            record("h1", f"{cadence}_holdout", weights, excess_t2,
                   HOLDOUT_START, HOLDOUT_END, ppy)

    # ---- H2: material-demand nowcast sleeve ----------------------------
    now_path = lt.DATA / "signals_nowcast.csv"
    if not now_path.exists() or pd.read_csv(now_path).empty:
        log.error("signals_nowcast.csv missing/empty — H2 skipped; run "
                  "scripts/07_signals.py (P5)")
        findings["h2"]["nowcast_monthly"] = {"status": "missing_signals"}
    elif excess_t3.empty:
        findings["h2"]["nowcast_monthly"] = {"status": "no_supplier_prices"}
    else:
        nowcast = pd.read_csv(now_path)
        # suppliers only — commodities are reference series, never P&L
        h2_tradeable = tradeable & set(uni["tier3"])
        weights = h2_weights(nowcast, args.turnover_cap, h2_tradeable)
        record("h2", "nowcast_monthly", weights, excess_t3,
               args.start, args.end, 12)
        if args.include_holdout:
            record("h2", "nowcast_monthly_holdout", weights, excess_t3,
                   HOLDOUT_START, HOLDOUT_END, 12)

    # ---- H2 trends-proxy sleeve (DECISIONS.md v1 addendum) --------------
    trends_path = lt.DATA / "signals_nowcast_trends.csv"
    if not trends_path.exists() or pd.read_csv(trends_path).empty:
        findings["h2"]["nowcast_trends_monthly"] = {"status": "missing_signals"}
    elif excess_t3.empty:
        findings["h2"]["nowcast_trends_monthly"] = {"status": "no_supplier_prices"}
    else:
        nowcast_tr = pd.read_csv(trends_path)
        weights_tr = h2_weights(nowcast_tr, args.turnover_cap,
                                tradeable & set(uni["tier3"]))
        record("h2", "nowcast_trends_monthly", weights_tr, excess_t3,
               args.start, args.end, 12)
        if isinstance(findings["h2"].get("nowcast_trends_monthly"), dict):
            findings["h2"]["nowcast_trends_monthly"]["downstream_source"] = \
                "google_trends_proxy (v1 addendum — NOT measured catalog mix)"
        if args.include_holdout:
            record("h2", "nowcast_trends_monthly_holdout", weights_tr,
                   excess_t3, HOLDOUT_START, HOLDOUT_END, 12)

    # commodities: reference series only, never P&L (CLAUDE.md)
    ref = {}
    for c in uni["commodities"]:
        if c in tradeable:
            ref[c] = round(float(lx.period_returns(
                returns_wide[[c]], args.start, args.end).iloc[0]), 4)
    findings["h2"]["reference_commodities_car"] = ref

    # ---- outputs --------------------------------------------------------
    findings["meta"] = {
        "run_date": date.today().isoformat(),
        "dev_window": [args.start, args.end],
        "holdout_included": bool(args.include_holdout),
        "cost_bps_per_side": args.cost_bps,
        "turnover_cap_oneway": args.turnover_cap,
        "universe_hash": universe_hash(),
        "note": "All pre-registered runs reported (objectivity charter). "
                "Metrics net of costs.",
    }
    with open(lt.REPORTS / "findings.json", "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)
    if period_rows:
        pd.DataFrame(period_rows).to_csv(
            lt.REPORTS / "backtest_results.csv", index=False)
    if equity_rows:
        pd.DataFrame(equity_rows).to_csv(
            lt.REPORTS / "equity_curves.csv", index=False)

    lines = ["# Trickle_Down backtest summary", "",
             f"Run {findings['meta']['run_date']} | window {args.start}..{args.end} | "
             f"costs {args.cost_bps}bps/side | turnover cap {args.turnover_cap}", "",
             "| strategy | sharpe | IR | hit rate | CAR | maxDD | rebalances |",
             "|---|---|---|---|---|---|---|"]
    for root in ("h1", "h2"):
        for key, m in findings[root].items():
            if not isinstance(m, dict) or "car" not in m:
                lines.append(f"| {root}_{key} | — status: "
                             f"{m.get('status', 'n/a') if isinstance(m, dict) else m} | | | | | |")
                continue
            lines.append(f"| {root}_{key} | {m.get('sharpe')} | {m.get('ir')} | "
                         f"{m.get('hit_rate')} | {m.get('car')} | "
                         f"{m.get('max_drawdown')} | {m.get('n_rebalances')} |")
    lines += ["", "Seasonal is the pre-registered primary; monthly is "
              "robustness. A negative result is a result (CLAUDE.md).",
              "Commodity CARs are reference only, never P&L."]
    (lt.REPORTS / "backtest_summary.md").write_text("\n".join(lines),
                                                    encoding="utf-8")
    log.info("findings.json, backtest_summary.md, results/equity CSVs written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
