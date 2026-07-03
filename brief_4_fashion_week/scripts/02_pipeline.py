"""Brief 4 / Phases 2-7 — pipeline from panel to deliverables.

P2: reuse ../data/prices_raw.csv
P3: compute event-level CARs/ARs via lib_event_study + during_FW_AR
P4: confounders (earnings within +/-10 trading days)
P5: 3 tests on full panel + per-city cohort cuts + index-level sanity check
P6: Excel — Overview (10 charts) + 4 per-city tabs
P7: Word — 7 sections, >=4 embedded charts
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import lib_doc as ld
import lib_event_study as les
import lib_excel as lx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("brief4_p2_7")

DATA = ROOT / "data"
REPORTS = ROOT / "reports"
IMG = REPORTS / "img"

PANEL_IN = DATA / "fw_events.csv"
EVENTS = DATA / "events.csv"
CONFOUND = DATA / "confounders_brief4.csv"
FINDINGS = DATA / "findings.json"

XLSX = REPORTS / "Fashion_Week_Aggregate_Event_Study.xlsx"
DOCX = REPORTS / "Fashion_Week_Aggregate_Findings.docx"


def fetch_earnings(ticker: str) -> set:
    try:
        df = yf.Ticker(ticker).earnings_dates
        if df is None or df.empty:
            return set()
        return set(pd.to_datetime(df.index).tz_localize(None).normalize())
    except Exception:
        return set()


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(PANEL_IN, parse_dates=["fw_start_date", "fw_end_date", "show_date"])
    log.info("panel in: %d rows", len(panel))

    prices = les.load_prices(PROJECT_ROOT / "data" / "prices_raw.csv")
    log.info("prices: %d rows %d tickers", len(prices), prices["ticker"].nunique())

    log.info("Phase 3: compute event-level returns")
    events, drops = les.compute_event_metrics(panel, prices)
    drops.to_csv(DATA / "events_dropped.csv", index=False)
    bad_cols = [c for c in events.columns if c.startswith(("CAR_", "AR_", "raw_", "benchmark_"))]
    bad_mask = events[bad_cols].apply(lambda c: ~np.isfinite(c)).any(axis=1)
    if bad_mask.sum():
        log.warning("dropping %d events with NaN/inf", int(bad_mask.sum()))
        events = events[~bad_mask].reset_index(drop=True)

    by_t = {t: g.sort_values("date").reset_index(drop=True) for t, g in prices.groupby("ticker")}
    during_fw = []
    for _, ev in events.iterrows():
        tk = ev["ticker"]; bench = les.TICKER_BENCH.get(tk)
        if tk not in by_t or bench not in by_t:
            during_fw.append(np.nan); continue
        s = by_t[tk]; b = by_t[bench][["date", "daily_return"]].rename(columns={"daily_return": "bench_ret"})
        sd = pd.to_datetime(ev["show_date"]); ed = pd.to_datetime(ev["fw_end_date"])
        win = s[(s["date"] >= sd) & (s["date"] <= ed)].merge(b, on="date", how="left").dropna(subset=["daily_return", "bench_ret"])
        during_fw.append(float((win["daily_return"] - win["bench_ret"]).sum()) if len(win) else np.nan)
    events["during_FW_AR"] = during_fw
    events.to_csv(EVENTS, index=False)
    log.info("wrote %s rows=%d", EVENTS, len(events))

    log.info("Phase 4: confounders")
    earnings_by_ticker: dict[str, set] = {}
    for tk in sorted(events["ticker"].unique()):
        earnings_by_ticker[tk] = fetch_earnings(tk)
        time.sleep(0.4)
    by_ticker_dates = {
        t: np.sort(np.array(g["date"].dt.normalize().unique(), dtype="datetime64[ns]"))
        for t, g in prices.groupby("ticker")
    }
    cf_rows = []
    for _, ev in events.iterrows():
        tk = ev["ticker"]; eset = earnings_by_ticker.get(tk, set())
        unknown = len(eset) == 0; within = False
        if not unknown and tk in by_ticker_dates:
            td = by_ticker_dates[tk]
            t0 = np.datetime64(pd.to_datetime(ev["trading_day_t0"]))
            i0_arr = np.where(td >= t0)[0]
            if len(i0_arr):
                i0 = int(i0_arr[0])
                lo = max(0, i0 - 10); hi = min(len(td) - 1, i0 + 10)
                window_days = set(pd.to_datetime(td[lo:hi + 1]).normalize())
                within = any(d in window_days for d in eset)
        cf_rows.append({
            "event_id": ev["event_id"], "ticker": tk,
            "earnings_within_10d": bool(within),
            "confounder_unknown": bool(unknown),
            "confounded": bool(within),
        })
    cf = pd.DataFrame(cf_rows); cf.to_csv(CONFOUND, index=False)
    log.info("wrote %s confounded=%d unknown=%d", CONFOUND, int(cf["confounded"].sum()), int(cf["confounder_unknown"].sum()))

    df = events.merge(cf, on=["event_id", "ticker"], how="left")

    log.info("Phase 5: stats")
    findings = {"n_events": int(len(df)), "n_companies": int(df["ticker"].nunique()),
                "n_weeks": int(panel.groupby(["city", "season", "year"]).ngroups)}

    findings["full_panel"] = {
        "n": int(len(df)),
        "test1": les.run_test1(df),
        "test2": les.run_test2(df, group_col="ticker", threshold=0.03),
    }
    curve = les.aggregate_car_curve(events, prices)
    findings["full_panel"]["test3"] = les.run_test3(curve)

    plt.figure(figsize=(10, 5))
    plt.plot(curve.index, curve.values, color="#222")
    plt.axhline(0, color="grey", linewidth=0.7)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--")
    plt.title("Brief 4 — Aggregate CAR (-30..+30) full panel")
    plt.xlabel("Trading day"); plt.ylabel("Mean CAR"); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(IMG / "agg_car.png", dpi=140); plt.close()

    city_results = {}
    for city in ["paris", "milan", "new_york", "london"]:
        sub = df[df["city"] == city]
        if len(sub) >= 5:
            city_results[city] = {
                "n": int(len(sub)),
                "test1": les.run_test1(sub),
                "test2": les.run_test2(sub, group_col="ticker", threshold=0.03),
            }
        else:
            city_results[city] = {"n": int(len(sub)), "skipped": "n<5"}
    findings["city_cohorts"] = city_results

    log.info("Phase 5b: index-level sanity check")
    idx_results = {}
    for city, idx_ticker in {"paris": "^FCHI", "milan": "FTSEMIB.MI", "new_york": "^GSPC", "london": "^FTSE"}.items():
        if idx_ticker not in by_t:
            idx_results[city] = {"index": idx_ticker, "skipped": "no price data"}; continue
        idx_df = by_t[idx_ticker]
        weeks = panel[panel["city"] == city][["fw_start_date", "fw_end_date"]].drop_duplicates()
        rets = []
        for _, w in weeks.iterrows():
            sub = idx_df[(idx_df["date"] >= w["fw_start_date"]) & (idx_df["date"] <= w["fw_end_date"])]
            if len(sub) >= 2:
                rets.append(float(sub["daily_return"].sum()))
        rets = np.array(rets, dtype=float)
        if len(rets) >= 5:
            t, p = stats.ttest_1samp(rets, 0.0)
            idx_results[city] = {
                "index": idx_ticker, "n_weeks": int(len(rets)),
                "mean_during_fw_log_return": float(np.mean(rets)),
                "t_stat_vs_0": float(t), "p_value": float(p),
                "flagged": bool(np.isfinite(t) and (abs(t) > 1.96 or p < 0.05)),
            }
        else:
            idx_results[city] = {"index": idx_ticker, "n_weeks": int(len(rets)), "skipped": "n<5"}
    findings["index_sanity_check"] = idx_results

    findings["any_flagged_full"] = bool(
        any(t["flagged"] for t in findings["full_panel"]["test1"])
        or findings["full_panel"]["test2"]["flagged"]
        or findings["full_panel"]["test3"]["flagged"]
    )

    FINDINGS.write_text(json.dumps(findings, indent=2, default=str))
    log.info("wrote %s any_flagged=%s", FINDINGS, findings["any_flagged_full"])

    log.info("Phase 6: Excel")
    build_excel(df, findings, prices)
    log.info("Phase 7: Word")
    build_doc(df, findings)
    log.info("Brief 4 complete.")
    return 0


def build_excel(df: pd.DataFrame, findings: dict, prices: pd.DataFrame) -> None:
    ts = list(range(-les.PRE, les.POST + 1))
    win_map = les.build_event_window(df, prices)
    rows = [{"event_id": eid, "t": int(r.t), "AR": float(r.AR)}
            for eid, w in win_map.items() for r in w.itertuples(index=False)]
    long = pd.DataFrame(rows)

    if not long.empty:
        long_sorted = long.sort_values(["event_id", "t"])
        long_sorted["cum"] = long_sorted.groupby("event_id")["AR"].cumsum()
        pivot = long_sorted.pivot(index="event_id", columns="t", values="cum").reindex(columns=ts).ffill(axis=1)
    else:
        pivot = pd.DataFrame()

    paths = []

    p1 = IMG / "ov1_agg.png"
    plt.figure(figsize=(10, 5))
    if not pivot.empty:
        m = pivot.mean(axis=0); p25 = pivot.quantile(0.25); p75 = pivot.quantile(0.75)
        plt.fill_between(ts, p25.values, p75.values, alpha=0.25, color="#3a6")
        plt.plot(ts, m.values, color="#222", linewidth=1.6)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("1) Aggregate CAR -30..+30 (25-75 band)"); plt.xlabel("Trading day"); plt.ylabel("CAR")
    plt.grid(alpha=0.3); plt.tight_layout(); plt.savefig(p1, dpi=140); plt.close()
    paths.append(p1)

    if not long.empty:
        eid_to_tk = dict(zip(df["event_id"], df["ticker"]))
        sub10 = long[(long["t"] >= -10) & (long["t"] <= 10)].assign(ticker=lambda d: d["event_id"].map(eid_to_tk))
        heat = sub10.groupby(["ticker", "t"])["AR"].mean().unstack().reindex(columns=range(-10, 11))
        p2 = IMG / "ov2_heatmap.png"
        plt.figure(figsize=(11, 6))
        sns.heatmap(heat, cmap="RdYlGn", center=0, cbar_kws={"label": "mean AR"})
        plt.title("2) Mean AR heatmap (rows=ticker, cols=trading day)")
        plt.tight_layout(); plt.savefig(p2, dpi=140); plt.close()
        paths.append(p2)

    p3 = IMG / "ov3_ar_t5_hist.png"
    x = df["AR_t5"].dropna() * 100
    plt.figure(figsize=(9, 5))
    if len(x):
        plt.hist(x, bins=30, edgecolor="white")
        plt.axvline(x.mean(), color="red", label=f"mean {x.mean():.2f}%")
        plt.axvline(x.median(), color="orange", linestyle="--", label=f"median {x.median():.2f}%")
        plt.legend()
    plt.title(f"3) AR_t5 histogram (n={len(x)})"); plt.xlabel("AR_t5 (%)"); plt.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(p3, dpi=140); plt.close()
    paths.append(p3)

    p4 = IMG / "ov4_yearly.png"
    df2 = df.copy(); df2["yr"] = pd.to_datetime(df2["show_date"]).dt.year
    yr = df2.groupby("yr")["CAR_0to5"].mean()
    plt.figure(figsize=(10, 4.5))
    plt.plot(yr.index, yr.values * 100, marker="o", color="#444"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("4) Yearly mean CAR_0to5"); plt.xlabel("Year"); plt.ylabel("Mean CAR_0to5 (%)")
    plt.grid(alpha=0.3); plt.tight_layout(); plt.savefig(p4, dpi=140); plt.close()
    paths.append(p4)

    p5 = IMG / "ov5_season.png"
    plt.figure(figsize=(10, 5))
    if not pivot.empty:
        for season, color in (("SS", "#1b8a5a"), ("FW", "#9b3a3a")):
            eids = df.loc[df["season"] == season, "event_id"]
            sub = pivot.loc[pivot.index.isin(eids)]
            if len(sub) >= 3:
                plt.plot(ts, sub.mean(axis=0).values, label=f"{season} ({len(sub)})", color=color)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("5) SS vs FW CAR"); plt.legend(); plt.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(p5, dpi=140); plt.close()
    paths.append(p5)

    p6 = IMG / "ov6_pure_vs_cong.png"
    df["entity_type"] = df["ticker"].map(les.ENTITY_TYPE)
    plt.figure(figsize=(10, 5))
    if not pivot.empty:
        for typ, color in (("Pure-play", "#1c4e80"), ("Conglomerate", "#a85d5d")):
            eids = df.loc[df["entity_type"] == typ, "event_id"]
            sub = pivot.loc[pivot.index.isin(eids)]
            if len(sub) >= 3:
                plt.plot(ts, sub.mean(axis=0).values, label=f"{typ} ({len(sub)})", color=color)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("6) Pure-play vs Conglomerate"); plt.legend(); plt.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(p6, dpi=140); plt.close()
    paths.append(p6)

    p7 = IMG / "ov7_confound.png"
    plt.figure(figsize=(10, 5))
    if not pivot.empty:
        for flag, color, label in ((True, "#a85d5d", "Confounded"), (False, "#1c4e80", "Clean")):
            eids = df.loc[df["confounded"] == flag, "event_id"]
            sub = pivot.loc[pivot.index.isin(eids)]
            if len(sub) >= 3:
                plt.plot(ts, sub.mean(axis=0).values, label=f"{label} ({len(sub)})", color=color)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("7) Confounded vs Clean"); plt.legend(); plt.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(p7, dpi=140); plt.close()
    paths.append(p7)

    p8 = IMG / "ov8_best_worst.png"
    sub = df.dropna(subset=["CAR_0to5"]).sort_values("CAR_0to5")
    nb = min(20, len(sub) // 2)
    bottom = sub.head(nb); top = sub.tail(nb)
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for ax, s, title, color in ((axes[0], bottom, f"Worst {nb}", "#a85d5d"),
                                 (axes[1], top, f"Best {nb}", "#1b8a5a")):
        labels = [f'{r["ticker"]} {r["city"][:3]}{r["season"]}{r["year"]}' for _, r in s.iterrows()]
        ax.barh(labels, s["CAR_0to5"].values * 100, color=color)
        ax.set_xlabel("CAR_0to5 (%)"); ax.set_title(title); ax.grid(alpha=0.3); ax.invert_yaxis()
    plt.tight_layout(); plt.savefig(p8, dpi=140); plt.close()
    paths.append(p8)

    p9 = IMG / "ov9_by_city.png"
    plt.figure(figsize=(10, 5))
    if not pivot.empty:
        for city, color in [("paris", "#1c4e80"), ("milan", "#1b8a5a"), ("new_york", "#a85d5d"), ("london", "#444")]:
            eids = df.loc[df["city"] == city, "event_id"]
            sub = pivot.loc[pivot.index.isin(eids)]
            if len(sub) >= 3:
                plt.plot(ts, sub.mean(axis=0).values, label=f"{city} ({len(sub)})", color=color)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("9) CAR by city (Paris/Milan/NY/London)"); plt.legend(); plt.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(p9, dpi=140); plt.close()
    paths.append(p9)

    p10 = IMG / "ov10_index_sanity.png"
    fig, ax = plt.subplots(figsize=(10, 5))
    cities = []; means = []; tstats = []
    for city, r in findings["index_sanity_check"].items():
        if "skipped" in r:
            continue
        cities.append(city); means.append(r["mean_during_fw_log_return"] * 100); tstats.append(r["t_stat_vs_0"])
    if cities:
        bars = ax.bar(cities, means, color=["#1c4e80", "#1b8a5a", "#a85d5d", "#444"][:len(cities)])
        for bar, t in zip(bars, tstats):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"t={t:.2f}", ha="center", va="bottom")
        ax.axhline(0, color="grey", linewidth=0.7)
    ax.set_title("10) Local-index mean log return DURING fashion week (sanity check)")
    ax.set_ylabel("Mean log return (%)"); ax.grid(alpha=0.3, axis="y")
    plt.tight_layout(); plt.savefig(p10, dpi=140); plt.close()
    paths.append(p10)

    wb, ws = lx.new_workbook("Overview")
    lx.write_title(ws, "Brief 4 — Fashion-Week Aggregate Effect")
    nxt = lx.write_kv_block(ws, [
        ("Total panel events", findings["n_events"]),
        ("Total fashion weeks", findings["n_weeks"]),
        ("Companies", findings["n_companies"]),
        ("Confounded", int(df["confounded"].sum())),
        ("Any test flagged (full)", "YES" if findings["any_flagged_full"] else "NO"),
    ])
    nxt = lx.write_test_table(ws, "Test 1 — Aggregate t-stat (full panel)",
                              ["Window", "n", "mean_CAR", "t_stat", "p_value", "flagged"],
                              [[r["window"], r["n"], r["mean_CAR"], r["t_stat"], r["p_value"],
                                "Y" if r["flagged"] else ""] for r in findings["full_panel"]["test1"]],
                              start_row=nxt)
    nxt = lx.write_test_table(ws, "Test 2 — Per-parent median CAR_0to5",
                              ["Ticker", "n", "median_CAR_0to5", "flagged"],
                              [[r["ticker"], r["n_events"], r["median_CAR_0to5"], "Y" if r["flagged"] else ""]
                               for r in findings["full_panel"]["test2"]["company_results"]],
                              start_row=nxt)
    nxt = lx.write_test_table(ws, "Test 3 — Peak deflection",
                              ["Peak |deflection|", "Threshold", "Flagged"],
                              [[round(findings["full_panel"]["test3"]["peak_deflection"], 4),
                                0.015, "Y" if findings["full_panel"]["test3"]["flagged"] else ""]],
                              start_row=nxt)
    nxt = lx.write_test_table(ws, "Index sanity check (does local index move during FW?)",
                              ["City", "Index", "n_weeks", "mean_log_return", "t_stat_vs_0", "p_value", "flagged"],
                              [[c, r.get("index", ""), r.get("n_weeks", 0),
                                round(r.get("mean_during_fw_log_return", 0), 4),
                                round(r.get("t_stat_vs_0", 0), 3),
                                round(r.get("p_value", 1), 4),
                                "Y" if r.get("flagged", False) else ""]
                               for c, r in findings["index_sanity_check"].items()],
                              start_row=nxt)
    lx.embed_images(ws, paths, start_row=nxt + 2)
    lx.autosize(ws)

    car_cols = ["CAR_pre30", "CAR_pre10", "CAR_pre5", "CAR_0to1", "CAR_0to5", "CAR_0to10", "CAR_0to30",
                "AR_t1", "AR_t5", "AR_t10", "during_FW_AR"]
    for city in ["paris", "milan", "new_york", "london"]:
        df_c = df[df["city"] == city].copy()
        if df_c.empty:
            continue
        ws_c = wb.create_sheet(title=city.replace("_", "-")[:31])
        ws_c["A1"] = f"{city.upper()} Fashion Week — {len(df_c)} panel events"
        ws_c["A1"].font = lx.TITLE_FONT
        cols = ["event_id", "season", "year", "ticker", "brands_showing", "fw_start_date", "fw_end_date",
                "trading_day_t0", *car_cols, "earnings_within_10d", "confounded"]
        cols = [c for c in cols if c in df_c.columns]
        first_data, last_data = lx.write_table(ws_c, df_c.sort_values(["year", "season"]), cols, start_row=3)
        if last_data >= first_data:
            car_idx = [cols.index(c) + 1 for c in car_cols if c in cols]
            lx.apply_car_conditional_formatting(ws_c, first_data, last_data, car_idx)
        lx.autosize(ws_c)

    wb.save(XLSX)
    log.info("wrote %s", XLSX)


def build_doc(df: pd.DataFrame, findings: dict) -> None:
    doc = ld.open_doc("Brief 4 — Fashion-Week Aggregate Effect — Findings")

    flagged = findings["any_flagged_full"]
    idx_check = findings["index_sanity_check"]
    idx_flagged = [c for c, r in idx_check.items() if r.get("flagged", False)]

    summary = (
        f"Across {findings['n_events']} (parent x fashion-week) panel events spanning "
        f"{findings['n_weeks']} fashion weeks ({findings['n_companies']} listed parents), "
        + ("at least one full-panel test flagged a meaningful effect."
           if flagged else
           "none of the three full-panel tests flagged a meaningful effect.")
        + " Index-level sanity check: "
        + (f"local indices flagged as moving abnormally during their fashion week in {len(idx_flagged)} of 4 cities ({', '.join(idx_flagged)})."
           if idx_flagged else
           "no local index showed abnormal movement during its fashion week — the broader market did not rotate around fashion weeks.")
    )
    ld.add_section(doc, 1, "Executive Summary", paragraphs=[summary])

    ld.add_section(doc, 2, "Methodology", paragraphs=[
        "Universe: 14 listed luxury parents from master CLAUDE.md, mapped to fashion weeks via "
        "extended brand list (Paris weeks include MC.PA brands LV/Dior/Loewe/Celine/Givenchy/Fendi, "
        "Kering brands Saint Laurent/Balenciaga/McQueen, and Hermès; Milan weeks include "
        "KER.PA via Gucci/Bottega, 1913.HK via Prada/Miu Miu, BC.MI, MONC.MI, SFER.MI, plus MC.PA via "
        "Fendi when in Milan; NY weeks include CPRI/TPR/PVH/RL; London is Burberry-only).",
        "Event source: synthetic fashion-week calendar generated from the well-documented annual "
        "convention (NYFW → LFW → MFW → PFW, sequential ~6-day weeks; SS in September, FW in February). "
        "The four governing bodies (FHCM, CMI, CFDA, BFC) do not publish historical archives in "
        "scrape-friendly format. Per the spec's fallback clause, we generated the calendar from "
        "convention. Date precision is ±3 days year-over-year; well within the ±30-day event window.",
        "Event window: -30 to +30 trading days. Returns: log abnormal vs. local broad-market index. "
        "CARs computed for the standard windows. Plus a brief-specific column during_FW_AR (sum of "
        "abnormal returns from t=0 through fw_end_date, ~5-7 trading days). Earnings within ±10 "
        "trading days flag confounded events.",
    ])

    ld.add_section(doc, 3, "Headline Findings")
    ld.add_subsection(doc, "3.1 Test 1 — Aggregate t-stats (full panel)")
    ld.add_table(doc, ["Window", "n", "mean CAR", "t-stat", "p-value", "flagged"],
                 [[r["window"], str(r["n"]), f"{r['mean_CAR']:.4f}",
                   f"{r['t_stat']:.3f}", f"{r['p_value']:.4f}", "Y" if r["flagged"] else ""]
                  for r in findings["full_panel"]["test1"]])

    ld.add_subsection(doc, "3.2 Test 2 — Per-parent median CAR_0to5")
    flagged_co = [r for r in findings["full_panel"]["test2"]["company_results"] if r["flagged"]]
    if flagged_co:
        names = [f"{r['ticker']} ({r['median_CAR_0to5']*100:+.2f}%)" for r in flagged_co]
        doc.add_paragraph("Flagged companies: " + ", ".join(names) + ".")
    else:
        doc.add_paragraph("No company exceeded the 3% median CAR_0to5 threshold.")

    ld.add_subsection(doc, "3.3 Test 3 — Aggregate CAR peak deflection")
    doc.add_paragraph(f"Peak: {findings['full_panel']['test3']['peak_deflection']*100:.2f}% "
                      + ("(flagged > 1.5%)" if findings['full_panel']['test3']['flagged'] else "(below 1.5%)"))
    ld.add_picture(doc, IMG / "agg_car.png")

    ld.add_section(doc, 4, "Per-City Observations")
    rows = []
    for city, r in findings["city_cohorts"].items():
        if "skipped" in r:
            rows.append([city, str(r["n"]), "—", "—", "—"]); continue
        ts1 = r["test1"]
        car5 = next((t for t in ts1 if t["window"] == "CAR_0to5"), None)
        rows.append([city, str(r["n"]),
                     f"{car5['mean_CAR']:.4f}" if car5 else "—",
                     f"{car5['t_stat']:.3f}" if car5 else "—",
                     "Y" if (car5 and car5["flagged"]) else ""])
    ld.add_table(doc, ["City", "n", "mean CAR_0to5", "t-stat (CAR_0to5)", "flagged"], rows)

    ld.add_section(doc, 5, "Index-Level Sanity Check + Confounding Analysis", paragraphs=[
        "The index-level sanity check asks: does the local broad-market index itself drift "
        "abnormally during fashion week? If yes, individual stock CARs vs. the local index are "
        "confounded by the index's own move. Across the four cities:",
    ])
    rows = []
    for city, r in findings["index_sanity_check"].items():
        if "skipped" in r:
            rows.append([city, r.get("index", ""), "—", "—", "—", "—", "skipped"]); continue
        rows.append([city, r["index"], str(r["n_weeks"]),
                     f"{r['mean_during_fw_log_return']*100:+.3f}%",
                     f"{r['t_stat_vs_0']:.3f}", f"{r['p_value']:.4f}",
                     "Y" if r["flagged"] else ""])
    ld.add_table(doc, ["City", "Index", "n_weeks", "mean log return", "t vs 0", "p-value", "flagged"], rows)
    n_conf = int(df["confounded"].sum())
    doc.add_paragraph(
        f"Earnings confounders: {n_conf} of {len(df)} panel events fall within ±10 trading days "
        "of an earnings release. Many fashion weeks coincide with earnings season (Feb FW + Q4 reports, Sept SS + Q3 reports), which is one reason the panel is not 'clean'."
    )
    ld.add_picture(doc, IMG / "ov10_index_sanity.png")

    ld.add_section(doc, 6, "Limitations", bullets=[
        "Synthetic calendar — fashion week start dates are generated from convention, not "
        "scraped from the four governing bodies. Real dates can drift ±3 days year-over-year.",
        "Conglomerate dilution: parents with brands across multiple cities (MC.PA in Paris+Milan, "
        "KER.PA in Paris+Milan) appear in multiple cohorts; their stock can't separately react to each.",
        "Local broad-market benchmark only. Sector benchmark (e.g., S&P Global Luxury) was not "
        "fetched; sector rotation is not isolated.",
        "Fashion weeks are calendared and anticipated to the day — markets price calendared events "
        "at scheduling, not occurrence — so a flat aggregate would be unsurprising.",
        "(Parent x week) panel rows are not statistically independent: weekly fashion calendars "
        "stack within a single month, and the same parent appears multiple times within a quarter.",
        "TOD.MI not in panel because no price data (delisted Sep 2024).",
    ])

    ld.add_section(doc, 7, "Phase 2 Hypotheses", bullets=[
        "Replace synthetic calendar with scraped governing-body archives (FHCM, CMI, CFDA, BFC) "
        "where available; reconcile against BoF and Vogue Runway for older dates.",
        "Add S&P Global Luxury Index (LXLU) as a sector benchmark and recompute "
        "(stock − local) − (LXLU − local) sector rotation.",
        "Single-show event study (Phase 1's runway brief) joined to fashion-week panel — does "
        "the aggregate week effect attribute back to specific shows?",
        "Drop overlapping events (parent appears in multiple weeks within 30 trading days) to "
        "address non-independence.",
        "Designer-debut interaction: weeks featuring a CD's debut runway should show stronger "
        "signal than steady-state weeks.",
        "Macro-control regression: control for VIX / 10y yield / FX (EUR-USD, USD-CNY) which "
        "move during European-vs-American fashion weeks.",
    ])

    for p in [IMG / "ov1_agg.png", IMG / "ov9_by_city.png", IMG / "ov7_confound.png", IMG / "ov6_pure_vs_cong.png"]:
        if p.exists():
            ld.add_picture(doc, p)

    ld.save_doc(doc, DOCX)
    log.info("wrote %s", DOCX)


if __name__ == "__main__":
    sys.exit(main())
