"""Brief 1 / Phases 2-7 — pipeline from scraped appointments to deliverables.

P2: reuse ../data/prices_raw.csv (no re-scrape)
P3: compute event-level CARs/ARs via lib_event_study
P4: fetch earnings dates per ticker; flag earnings_within_10d
P5: three tests + pre_leaked TRUE/FALSE/UNKNOWN cohort + leaked-vs-not t-test
P6: build Excel deliverable via lib_excel
P7: build Word doc via lib_doc
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
log = logging.getLogger("brief1_p2_7")

DATA = ROOT / "data"
REPORTS = ROOT / "reports"
IMG = REPORTS / "img"

APPS = DATA / "cd_appointments.csv"
EVENTS = DATA / "events.csv"
CONFOUND = DATA / "confounders_brief1.csv"
FINDINGS = DATA / "findings.json"

XLSX = REPORTS / "CD_Appointments_Event_Study.xlsx"
DOCX = REPORTS / "CD_Appointments_Findings.docx"


def fetch_earnings(ticker: str) -> set:
    try:
        df = yf.Ticker(ticker).earnings_dates
        if df is None or df.empty:
            return set()
        return set(pd.to_datetime(df.index).tz_localize(None).normalize())
    except Exception as e:
        log.warning("earnings %s: %s", ticker, e)
        return set()


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)

    apps = pd.read_csv(APPS)
    apps["show_date"] = pd.to_datetime(apps["show_date"])
    log.info("loaded %d appointments", len(apps))

    prices = les.load_prices(PROJECT_ROOT / "data" / "prices_raw.csv")
    log.info("loaded %d price rows %d tickers", len(prices), prices["ticker"].nunique())

    log.info("Phase 3: computing event metrics")
    events, drops = les.compute_event_metrics(apps, prices)
    drops.to_csv(DATA / "events_dropped.csv", index=False)
    n_bad = events[[c for c in events.columns if c.startswith(("CAR_", "AR_", "raw_", "benchmark_"))]].apply(
        lambda c: ~np.isfinite(c)
    ).any(axis=1).sum()
    if n_bad:
        log.warning("dropping %d events with NaN/inf in computed cols", n_bad)
        bad_mask = events[[c for c in events.columns if c.startswith(("CAR_", "AR_", "raw_", "benchmark_"))]].apply(
            lambda c: ~np.isfinite(c)
        ).any(axis=1)
        events = events[~bad_mask].reset_index(drop=True)
    events.to_csv(EVENTS, index=False)
    log.info("wrote %s rows=%d (dropped %d)", EVENTS, len(events), len(drops))

    log.info("Phase 4: confounders (earnings ±10 trading days)")
    earnings_by_ticker: dict[str, set] = {}
    for tk in sorted(events["ticker"].unique()):
        earnings_by_ticker[tk] = fetch_earnings(tk)
        time.sleep(0.5)
    by_ticker_dates = {
        t: np.sort(np.array(g["date"].dt.normalize().unique(), dtype="datetime64[ns]"))
        for t, g in prices.groupby("ticker")
    }
    cf_rows = []
    for _, ev in events.iterrows():
        tk = ev["ticker"]
        eset = earnings_by_ticker.get(tk, set())
        unknown = len(eset) == 0
        within = False
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
    cf = pd.DataFrame(cf_rows)
    cf.to_csv(CONFOUND, index=False)
    log.info("wrote %s confounded=%d unknown=%d", CONFOUND,
             int(cf["confounded"].sum()), int(cf["confounder_unknown"].sum()))

    df = events.merge(cf, on=["event_id", "ticker"], how="left")

    log.info("Phase 5: three tests + cohort cuts")
    findings = {}

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
    plt.title("Brief 1 — Aggregate CAR (-30..+30)")
    plt.xlabel("Trading day"); plt.ylabel("Mean CAR")
    plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(IMG / "agg_car.png", dpi=140); plt.close()

    cohort_results = {}
    for label in ("UNKNOWN", "TRUE", "FALSE"):
        sub = df[df["pre_leaked"].astype(str).str.upper() == label]
        if len(sub) >= 5:
            cohort_results[label] = {
                "n": int(len(sub)),
                "test1": les.run_test1(sub),
            }
        else:
            cohort_results[label] = {"n": int(len(sub)), "skipped": "n<5"}
    findings["pre_leaked_cohorts"] = cohort_results

    a = df.loc[df["pre_leaked"].astype(str).str.upper() == "TRUE", "CAR_0to5"].dropna().values
    b = df.loc[df["pre_leaked"].astype(str).str.upper() == "FALSE", "CAR_0to5"].dropna().values
    if len(a) >= 5 and len(b) >= 5:
        t, p = stats.ttest_ind(a, b, equal_var=False)
        findings["leaked_vs_not_t_test"] = {
            "n_leaked": int(len(a)), "n_not": int(len(b)),
            "t_stat": float(t), "p_value": float(p)
        }
    else:
        findings["leaked_vs_not_t_test"] = {
            "skipped": "insufficient cohort sizes",
            "n_leaked": int(len(a)), "n_not": int(len(b)),
        }

    findings["any_flagged_full"] = bool(
        any(t["flagged"] for t in findings["full_panel"]["test1"])
        or findings["full_panel"]["test2"]["flagged"]
        or findings["full_panel"]["test3"]["flagged"]
    )
    findings["n_events"] = int(len(df))
    findings["n_companies"] = int(df["ticker"].nunique())

    FINDINGS.write_text(json.dumps(findings, indent=2, default=str))
    log.info("wrote %s any_flagged=%s", FINDINGS, findings["any_flagged_full"])

    log.info("Phase 6: Excel")
    build_excel(df, findings, prices)
    log.info("Phase 7: Word")
    build_doc(df, findings)
    log.info("Brief 1 complete.")
    return 0


def build_excel(df: pd.DataFrame, findings: dict, prices: pd.DataFrame) -> None:
    ts = list(range(-les.PRE, les.POST + 1))
    win_map = les.build_event_window(df, prices)
    rows = [{"event_id": eid, "t": int(r.t), "AR": float(r.AR)}
            for eid, w in win_map.items() for r in w.itertuples(index=False)]
    long = pd.DataFrame(rows)

    paths = []
    if not long.empty:
        long_sorted = long.sort_values(["event_id", "t"])
        long_sorted["cum"] = long_sorted.groupby("event_id")["AR"].cumsum()
        pivot = long_sorted.pivot(index="event_id", columns="t", values="cum").reindex(columns=ts).ffill(axis=1)
        m = pivot.mean(axis=0); p25 = pivot.quantile(0.25); p75 = pivot.quantile(0.75)
    else:
        pivot = pd.DataFrame(); m = pd.Series(dtype=float)

    p1 = IMG / "ov1_agg.png"
    plt.figure(figsize=(10, 5))
    if not m.empty:
        plt.fill_between(ts, p25.values, p75.values, alpha=0.25, color="#3a6")
        plt.plot(ts, m.values, color="#222", linewidth=1.6)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("1) Aggregate CAR (-30..+30) with 25-75 band"); plt.xlabel("Trading day"); plt.ylabel("CAR")
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
        plt.hist(x, bins=max(8, min(20, len(x) // 2)), edgecolor="white")
        plt.axvline(x.mean(), color="red", label=f"mean {x.mean():.2f}%")
        plt.axvline(x.median(), color="orange", linestyle="--", label=f"median {x.median():.2f}%")
        plt.legend()
    plt.title(f"3) AR_t5 histogram (n={len(x)})")
    plt.xlabel("AR_t5 (%)"); plt.grid(alpha=0.3); plt.tight_layout()
    plt.savefig(p3, dpi=140); plt.close()
    paths.append(p3)

    p4 = IMG / "ov4_yearly.png"
    df2 = df.copy()
    df2["year"] = pd.to_datetime(df2["show_date"]).dt.year
    yr = df2.groupby("year")["CAR_0to5"].mean()
    plt.figure(figsize=(10, 4.5))
    plt.plot(yr.index, yr.values * 100, marker="o", color="#444")
    plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("4) Yearly mean CAR_0to5"); plt.xlabel("Year"); plt.ylabel("Mean CAR_0to5 (%)")
    plt.grid(alpha=0.3); plt.tight_layout(); plt.savefig(p4, dpi=140); plt.close()
    paths.append(p4)

    p5 = IMG / "ov5_appt_type.png"
    plt.figure(figsize=(10, 5))
    if not pivot.empty:
        for atype, color in [("debut", "#1b8a5a"), ("replacement", "#9b3a3a"), ("role_creation", "#1c4e80")]:
            eids = df.loc[df["appointment_type"] == atype, "event_id"]
            sub = pivot.loc[pivot.index.isin(eids)]
            if len(sub) >= 3:
                plt.plot(ts, sub.mean(axis=0).values, label=f"{atype} ({len(sub)})", color=color)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("5) Mean CAR by appointment type"); plt.xlabel("Trading day"); plt.ylabel("CAR")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout(); plt.savefig(p5, dpi=140); plt.close()
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
    plt.title("6) Pure-play vs Conglomerate CAR"); plt.xlabel("Trading day"); plt.ylabel("CAR")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout(); plt.savefig(p6, dpi=140); plt.close()
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
    plt.title("7) Confounded vs Clean CAR"); plt.xlabel("Trading day"); plt.ylabel("CAR")
    plt.legend(); plt.grid(alpha=0.3); plt.tight_layout(); plt.savefig(p7, dpi=140); plt.close()
    paths.append(p7)

    p8 = IMG / "ov8_best_worst.png"
    sub = df.dropna(subset=["CAR_0to5"]).sort_values("CAR_0to5")
    nb = min(10, len(sub) // 2)
    bottom = sub.head(nb); top = sub.tail(nb)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, s, title, color in ((axes[0], bottom, f"Worst {nb} (CAR_0to5)", "#a85d5d"),
                                 (axes[1], top, f"Best {nb} (CAR_0to5)", "#1b8a5a")):
        labels = [f'{r["ticker"]} {r["brand"][:14]}' for _, r in s.iterrows()]
        ax.barh(labels, s["CAR_0to5"].values * 100, color=color)
        ax.set_xlabel("CAR_0to5 (%)"); ax.set_title(title); ax.grid(alpha=0.3); ax.invert_yaxis()
    plt.tight_layout(); plt.savefig(p8, dpi=140); plt.close()
    paths.append(p8)

    p9 = IMG / "ov9_pre_leaked.png"
    plt.figure(figsize=(10, 5))
    if not pivot.empty:
        for label, color in [("UNKNOWN", "#888"), ("TRUE", "#1b8a5a"), ("FALSE", "#a85d5d")]:
            eids = df.loc[df["pre_leaked"].astype(str).str.upper() == label, "event_id"]
            sub = pivot.loc[pivot.index.isin(eids)]
            if len(sub) >= 3:
                plt.plot(ts, sub.mean(axis=0).values, label=f"pre_leaked={label} ({len(sub)})", color=color)
    plt.axvline(0, color="grey", linewidth=0.7, linestyle="--"); plt.axhline(0, color="grey", linewidth=0.7)
    plt.title("9) pre_leaked cohort CARs (HYPOTHESIS-OF-INTEREST)")
    plt.xlabel("Trading day"); plt.ylabel("CAR"); plt.legend(); plt.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(p9, dpi=140); plt.close()
    paths.append(p9)

    wb, ws = lx.new_workbook("Overview")
    lx.write_title(ws, "Brief 1 — Creative-Director Appointments")
    nxt = lx.write_kv_block(ws, [
        ("Total events", findings["n_events"]),
        ("Companies", findings["n_companies"]),
        ("Confounded", int(df["confounded"].sum())),
        ("Confounder unknown", int(df["confounder_unknown"].sum())),
        ("Any test flagged (full)", "YES" if findings["any_flagged_full"] else "NO"),
        ("pre_leaked TRUE cohort n", findings["pre_leaked_cohorts"]["TRUE"]["n"]),
        ("pre_leaked FALSE cohort n", findings["pre_leaked_cohorts"]["FALSE"]["n"]),
        ("pre_leaked UNKNOWN cohort n", findings["pre_leaked_cohorts"]["UNKNOWN"]["n"]),
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
    nxt = lx.write_test_table(ws, "Test 3 — Peak deflection of aggregate curve",
                              ["Peak |deflection|", "Threshold", "Flagged"],
                              [[round(findings["full_panel"]["test3"]["peak_deflection"], 4),
                                0.015, "Y" if findings["full_panel"]["test3"]["flagged"] else ""]],
                              start_row=nxt)
    if "t_stat" in findings.get("leaked_vs_not_t_test", {}):
        lvn = findings["leaked_vs_not_t_test"]
        nxt = lx.write_test_table(ws, "Leaked vs Not — t-test on CAR_0to5",
                                  ["n_leaked", "n_not", "t_stat", "p_value"],
                                  [[lvn["n_leaked"], lvn["n_not"], round(lvn["t_stat"], 3),
                                    round(lvn["p_value"], 4)]],
                                  start_row=nxt)
    lx.embed_images(ws, paths, start_row=nxt + 2)
    lx.autosize(ws)

    car_cols_global = ["CAR_pre30", "CAR_pre10", "CAR_pre5",
                       "CAR_0to1", "CAR_0to5", "CAR_0to10", "CAR_0to30",
                       "AR_t1", "AR_t5", "AR_t10"]
    parent_counts = df["ticker"].value_counts()
    for ticker, n in parent_counts.items():
        if n < 2:
            continue
        ws_p = wb.create_sheet(title=ticker[:31])
        df_p = df[df["ticker"] == ticker].copy()
        ws_p["A1"] = f"{les.COMPANY_NAME.get(ticker, ticker)} ({ticker}) — {n} appointments"
        ws_p["A1"].font = lx.TITLE_FONT
        cols = ["event_id", "brand", "appointment_type", "show_date", "appointed_designer_name",
                "outgoing_designer_name", "pre_leaked", "trading_day_t0", "local_index_used",
                *car_cols_global, "earnings_within_10d", "confounded"]
        cols = [c for c in cols if c in df_p.columns]
        first_data, last_data = lx.write_table(ws_p, df_p, cols, start_row=3)
        if last_data >= first_data:
            car_idx = [cols.index(c) + 1 for c in car_cols_global if c in cols]
            lx.apply_car_conditional_formatting(ws_p, first_data, last_data, car_idx)
        lx.autosize(ws_p)

    wb.save(XLSX)
    log.info("wrote %s", XLSX)


def build_doc(df: pd.DataFrame, findings: dict) -> None:
    doc = ld.open_doc("Brief 1 — Creative-Director Appointments — Findings")

    flagged = findings["any_flagged_full"]
    pre_leaked_summary = (
        f"pre_leaked split: TRUE={findings['pre_leaked_cohorts']['TRUE']['n']}, "
        f"FALSE={findings['pre_leaked_cohorts']['FALSE']['n']}, "
        f"UNKNOWN={findings['pre_leaked_cohorts']['UNKNOWN']['n']}."
    )
    summary = (
        f"Across {findings['n_events']} creative-director appointment events at "
        f"{findings['n_companies']} listed luxury parents, "
        + ("at least one of the three full-panel tests flagged a meaningful effect."
           if flagged else
           "none of the three full-panel tests flagged a meaningful effect.")
        + " " + pre_leaked_summary
        + " Note that pre_leaked status was UNKNOWN for all events because the rumor-history "
        + "scrape was not run (Wikipedia primary source); the leaked-vs-not cohort cut therefore "
        + "could not be performed in Phase 1."
    )
    ld.add_section(doc, 1, "Executive Summary", paragraphs=[summary])

    ld.add_section(doc, 2, "Methodology", paragraphs=[
        "Universe: 14 listed luxury parents from the master CLAUDE.md, with extended brand "
        "list including LVMH (Louis Vuitton, Dior, Loewe, Celine, Givenchy, Fendi, Marc Jacobs), "
        "Kering (Gucci, Saint Laurent, Bottega Veneta, Balenciaga, Alexander McQueen, Brioni), "
        "Capri (Michael Kors, Versace, Jimmy Choo), Tapestry (Coach, Kate Spade, Stuart "
        "Weitzman), PVH (Calvin Klein, Tommy Hilfiger), and pure-plays.",
        "Event source: Wikipedia per-brand articles, parsed for sentences with 'creative "
        "director'/'appointed'/'named' patterns near absolute or month-resolution dates. "
        "Wikipedia was used because IR press archives, BoF, and WWD are paywalled or "
        "Cloudflare-protected. The spec lists Wikipedia as a fallback; we used it as primary.",
        "Event window: -30 to +30 trading days. Returns: log abnormal vs. local broad-market "
        "index. CARs computed for the standard windows; t=0 is the announcement date. "
        "Earnings dates flagged via yfinance; events within ±10 trading days of an earnings "
        "release are marked confounded.",
    ])

    ld.add_section(doc, 3, "Headline Findings")
    ld.add_subsection(doc, "3.1 Test 1 — Aggregate t-stats (full panel)")
    ld.add_table(doc, ["Window", "n", "mean CAR", "t-stat", "p-value", "flagged"],
                 [[r["window"], str(r["n"]), f"{r['mean_CAR']:.4f}",
                   f"{r['t_stat']:.3f}", f"{r['p_value']:.4f}",
                   "Y" if r["flagged"] else ""] for r in findings["full_panel"]["test1"]])

    ld.add_subsection(doc, "3.2 Test 2 — Per-parent median CAR_0to5")
    flagged_co = [r for r in findings["full_panel"]["test2"]["company_results"] if r["flagged"]]
    if flagged_co:
        names = [f"{r['ticker']} ({r['median_CAR_0to5']*100:+.2f}%)" for r in flagged_co]
        doc.add_paragraph("Flagged companies (|median CAR_0to5| > 3%): " + ", ".join(names) + ".")
    else:
        doc.add_paragraph("No company exceeded the 3% median CAR_0to5 threshold.")

    ld.add_subsection(doc, "3.3 Test 3 — Aggregate CAR peak deflection")
    doc.add_paragraph(
        f"Peak absolute deflection: {findings['full_panel']['test3']['peak_deflection']*100:.2f}% "
        + ("(flagged, > 1.5%)" if findings['full_panel']['test3']['flagged'] else "(below 1.5%)")
    )
    ld.add_picture(doc, IMG / "agg_car.png")

    ld.add_section(doc, 4, "Per-Parent / Brand-Level Observations")
    co = pd.DataFrame(findings["full_panel"]["test2"]["company_results"]).copy()
    co["abs_med"] = co["median_CAR_0to5"].abs()
    co = co.sort_values("abs_med", ascending=False)
    bullets = []
    for _, r in co.head(5).iterrows():
        nm = les.COMPANY_NAME.get(r["ticker"], r["ticker"])
        bullets.append(f"{nm} ({r['ticker']}): n={int(r['n_events'])}, median CAR_0to5={r['median_CAR_0to5']*100:+.2f}%")
    ld.add_section(doc, None, "", bullets=bullets) if False else [doc.add_paragraph(b, style="List Bullet") for b in bullets]
    ld.add_table(doc, ["Ticker", "Company", "n", "median CAR_0to5"],
                 [[r["ticker"], les.COMPANY_NAME.get(r["ticker"], r["ticker"]),
                   str(int(r["n_events"])), f"{r['median_CAR_0to5']*100:+.2f}%"]
                  for _, r in co.sort_values("ticker").iterrows()])
    brand_breakdown = df.groupby(["ticker", "brand"]).size().rename("n").reset_index().sort_values(["ticker", "n"], ascending=[True, False])
    ld.add_subsection(doc, "Brand-level appointment counts within parents")
    ld.add_table(doc, ["Ticker", "Brand", "n appointments"],
                 [[r["ticker"], r["brand"], str(int(r["n"]))] for _, r in brand_breakdown.iterrows()])

    ld.add_section(doc, 5, "Confounding & pre_leaked Cohort Analysis", paragraphs=[
        f"{int(df['confounded'].sum())} of {len(df)} events fall within ±10 trading days of "
        f"an earnings release; {int(df['confounder_unknown'].sum())} have unknown earnings status.",
        "All events have pre_leaked=UNKNOWN because the BoF/WWD rumor-history scrape was not "
        "run (sources paywalled). The TRUE-vs-FALSE cohort t-test therefore could not be "
        "performed in Phase 1. The pre_leaked overlay chart in the Excel deliverable shows "
        "only the UNKNOWN cohort curve.",
    ])
    ld.add_picture(doc, IMG / "ov7_confound.png")

    ld.add_section(doc, 6, "Limitations", bullets=[
        "Wikipedia coverage of CD appointments is uneven: well-documented for major recent "
        "appointments, sparse for older ones. Many appointments are missed.",
        "Date precision varies: only events with month-resolution dates were retained; some "
        "events are anchored at the 15th of the month and may be ±15 days from the true "
        "press-release date.",
        "pre_leaked flag is UNKNOWN for all events because the rumor-history check was not "
        "feasible without paid BoF/WWD access.",
        "Sample size (~31 events) is small for an event study; the detection threshold is "
        "correspondingly high.",
        "Only Wikipedia was used as a source; IR press archives may have additional events or "
        "more precise dates.",
    ])

    ld.add_section(doc, 7, "Phase 2 Hypotheses", bullets=[
        "Run the rumor-history scrape against BoF and WWD with paid access to fill the "
        "pre_leaked flag and run the leaked-vs-not cohort cut as designed.",
        "Cross-reference Wikipedia-derived events against IR press releases for date precision.",
        "Split debut (a designer's first appointment as CD) vs replacement appointments.",
        "Test whether the parent-stock reaction varies by the prior CD's tenure length.",
        "Add a sector benchmark in addition to the local broad index.",
        "Investigate the announcement vs first-collection split (do markets react to the "
        "appointment news, or wait until the runway debut?).",
    ])

    for p in [IMG / "ov1_agg.png", IMG / "ov9_pre_leaked.png", IMG / "ov5_appt_type.png", IMG / "ov6_pure_vs_cong.png"]:
        if p.exists():
            ld.add_picture(doc, p)

    ld.save_doc(doc, DOCX)
    log.info("wrote %s", DOCX)


if __name__ == "__main__":
    sys.exit(main())
