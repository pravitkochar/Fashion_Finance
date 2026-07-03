"""P4/P5 — build the two pre-registered signals (see CLAUDE.md, DECISIONS.md).

H1 adoption-speed: at each rebalance date T, score each retailer by how well
its downstream mix CHANGES over the trailing window tracked the direction
implied by the last runway season vector known BEFORE that window began
(runway info strictly precedes the adoption being measured). Cross-sectional
terciles: long the top, short the bottom. Cadences: seasonal (primary) and
monthly (robustness).

H2 material-demand nowcast (monthly): z-score of the cross-retailer mean
downstream share per material vs its trailing 12 months; mapped to the
supplier tickers in universe.json.

Point-in-time: ALL mix reads go through PITStore, whose only accessors apply
lt.filter_known_asof. Raw frames are private to the store — signal code
cannot see unfiltered data.

Outputs: data/signals_adoption.csv, data/signals_nowcast.csv (contracts in
lib_trickle), and data/signals_nowcast_trends.csv — the H2 nowcast computed
from the Google Trends PROXY per the DECISIONS.md v1 feasibility addendum
(retailer-level history isn't retroactively observable; trends is the
labeled stand-in until ≥24 months of measured mix accumulate).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

import lib_trickle as lt

log = lt.get_logger("07_signals")

WINDOW_MONTHS = 12    # trailing adoption window (H1)
MIN_MONTHS = 6        # retailer data floor inside the window (H1)
MIN_MATERIALS = 6     # materials needed for a score (H1)
MIN_RETAILERS = 6     # cross-section floor per rebalance date (H1)
NOWCAST_TRAIL = 12    # trailing months for the z-score (H2)
Z_GATE = 1.0          # |z| threshold for long/short (H2)


class PITStore:
    """The no-look-ahead gate. Signal code never touches the raw frames."""

    def __init__(self, runway_season: pd.DataFrame, downstream: pd.DataFrame):
        self.__rw = runway_season
        self.__dm = downstream

    def runway_asof(self, asof) -> pd.DataFrame:
        return lt.filter_known_asof(self.__rw, asof)

    def downstream_asof(self, asof) -> pd.DataFrame:
        return lt.filter_known_asof(self.__dm, asof)


def load_store() -> PITStore | None:
    rmix = lt.read_csv_or_empty(lt.DATA / "runway_mix.csv")
    dmix = lt.read_csv_or_empty(lt.DATA / "downstream_mix.csv")
    if rmix.empty or dmix.empty:
        log.warning("runway_mix.csv / downstream_mix.csv missing or empty — "
                    "measured-mix signals (H1, measured H2) unavailable; run "
                    "04_material_mix.py first")
        return None
    rmix = rmix[rmix["level"] == "season"].copy()
    dmix = dmix[~dmix["thin_sample"].astype(str).str.lower().eq("true")].copy()
    mats = set(lt.signal_materials())
    return PITStore(rmix[rmix["material"].isin(mats)],
                    dmix[dmix["material"].isin(mats)])


def load_trends_store() -> PITStore | None:
    """Trends-proxy downstream frame (DECISIONS.md v1 addendum).

    Per-material monthly mean of that material's trends_terms, shaped like
    downstream_mix (month, material, share). PIT: month M's value is only
    final once M ends, so known_date = first day of the following month.
    """
    tr = lt.read_csv_or_empty(lt.TRENDS / "trends.csv")
    if tr.empty:
        log.warning("trends.csv missing/empty — trends-proxy H2 unavailable; "
                    "run 05_google_trends.py first")
        return None
    tr = tr[(tr["term_type"] == "material")
            & tr["material"].isin(lt.signal_materials())].copy()
    if tr.empty:
        log.warning("trends.csv has no material-term rows — proxy unavailable")
        return None
    tr["month"] = tr["date"].astype(str).str.slice(0, 7)
    g = (tr.groupby(["month", "material"])["value"].mean()
         .reset_index().rename(columns={"value": "share"}))
    ends = pd.PeriodIndex(g["month"], freq="M").end_time.normalize() \
        + pd.Timedelta(days=1)
    g["known_date"] = [d.date().isoformat() for d in ends]
    g["retailer"] = "TRENDS_PROXY"
    return PITStore(pd.DataFrame(), g)


# ------------------------------------------------------------------ H1 ------

def adoption_score(store: PITStore, retailer: str, T: date) -> float | None:
    dm = store.downstream_asof(T)
    sub = dm[dm["retailer"] == retailer]
    if sub.empty:
        return None
    months = sorted(sub["month"].unique())[-WINDOW_MONTHS:]
    if len(months) < MIN_MONTHS:
        return None
    window_start = pd.Timestamp(f"{months[0]}-01")

    # last season vector known strictly before the window began
    rw = store.runway_asof(T)
    prior = rw[pd.to_datetime(rw["known_date"]) < window_start]
    if prior.empty:
        return None
    last_season = prior.loc[pd.to_datetime(prior["known_date"]).idxmax(),
                            "season_code"]
    runway_vec = (prior[prior["season_code"] == last_season]
                  .set_index("material")["share"])

    first_vec = (sub[sub["month"] == months[0]]
                 .set_index("material")["share"])
    last_vec = (sub[sub["month"] == months[-1]]
                .set_index("material")["share"])

    mats = runway_vec.index.intersection(first_vec.index).intersection(
        last_vec.index)
    if len(mats) < MIN_MATERIALS:
        return None
    actual = (last_vec[mats] - first_vec[mats]).astype(float)
    implied = (runway_vec[mats] - first_vec[mats]).astype(float)
    if actual.std() == 0 or implied.std() == 0:
        return None
    return float(np.corrcoef(actual, implied)[0, 1])


def seasonal_dates(start: date, end: date) -> list[date]:
    out = []
    for code in lt.iter_seasons(2016, until=end):
        d = lt.season_known_date(code) + timedelta(days=1)
        if start <= d <= end:
            out.append(d)
    return out


def monthly_dates(start: date, end: date) -> list[date]:
    first = max(start, date(2016, 7, 1))
    periods = pd.period_range(pd.Period(first, freq="M"),
                              pd.Period(end, freq="M"), freq="M")
    return [p.start_time.date() for p in periods
            if start <= p.start_time.date() <= end]


def build_h1(store: PITStore, cadence: str, dates: list[date],
             retailer_ticker: dict[str, str]) -> pd.DataFrame:
    rows, skipped = [], 0
    for T in dates:
        scored = []
        for retailer, ticker in retailer_ticker.items():
            s = adoption_score(store, retailer, T)
            if s is not None and not np.isnan(s):
                scored.append((ticker, s))
        if len(scored) < MIN_RETAILERS:
            skipped += 1
            log.info("H1 %s %s: only %d scored retailers (need %d) — "
                     "skipped", cadence, T, len(scored), MIN_RETAILERS)
            continue
        scored.sort(key=lambda x: -x[1])
        n = len(scored)
        n_leg = max(1, n // 3)
        for rank, (ticker, s) in enumerate(scored, start=1):
            if rank <= n_leg:
                w = 1.0 / n_leg
            elif rank > n - n_leg:
                w = -1.0 / n_leg
            else:
                w = 0.0
            rows.append({"rebalance_date": T.isoformat(), "ticker": ticker,
                         "score": round(s, 6), "rank": rank,
                         "weight": round(w, 6), "cadence": cadence})
    log.info("H1 %s: %d rebalance dates used, %d skipped",
             cadence, len(dates) - skipped, skipped)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ H2 ------

def material_tickers() -> dict[str, list[str]]:
    uni = lt.load_universe()
    out: dict[str, list[str]] = {}
    for entry in uni["tier3_suppliers"] + uni["commodities"]:
        for m in entry.get("materials", []):
            out.setdefault(m, []).append(entry["ticker"])
    return out


def build_h2(store: PITStore, dates: list[date]) -> pd.DataFrame:
    mat2tick = material_tickers()
    rows = 0
    out = []
    for T in dates:
        dm = store.downstream_asof(T)
        if dm.empty:
            continue
        mean_share = (dm.groupby(["month", "material"])["share"].mean()
                      .reset_index())
        for mat, tickers in sorted(mat2tick.items()):
            series = (mean_share[mean_share["material"] == mat]
                      .sort_values("month")["share"])
            if len(series) < NOWCAST_TRAIL + 1:
                continue
            x = float(series.iloc[-1])
            trail = series.iloc[-(NOWCAST_TRAIL + 1):-1]
            mu, sd = float(trail.mean()), float(trail.std(ddof=1))
            if not np.isfinite(sd) or sd == 0:
                z, direction = np.nan, "flat"
            else:
                z = (x - mu) / sd
                direction = ("long" if z > Z_GATE
                             else "short" if z < -Z_GATE else "flat")
            out.append({"date": T.isoformat(), "material": mat,
                        "nowcast_z": round(z, 4) if np.isfinite(z) else np.nan,
                        "direction": direction,
                        "tickers": ";".join(tickers)})
            rows += 1
    log.info("H2: %d (date, material) nowcast rows", rows)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- main ------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cadence", choices=["seasonal", "monthly", "both"],
                    default="both")
    ap.add_argument("--h2-source", choices=["measured", "trends", "both"],
                    default="both")
    ap.add_argument("--start", default="2016-04-01", help="ISO date")
    ap.add_argument("--end", default=None, help="ISO date (default today)")
    args = ap.parse_args()
    lt.ensure_dirs()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()

    store = load_store()
    uni = lt.load_universe()
    retailer_ticker = {r["key"]: r["ticker"] for r in uni["tier2_retailers"]
                       if r["ticker"]}

    if store is not None:
        frames = []
        if args.cadence in ("seasonal", "both"):
            frames.append(build_h1(store, "seasonal",
                                   seasonal_dates(start, end), retailer_ticker))
        if args.cadence in ("monthly", "both"):
            frames.append(build_h1(store, "monthly",
                                   monthly_dates(start, end), retailer_ticker))
        h1 = pd.concat([f for f in frames if not f.empty], ignore_index=True) \
            if any(not f.empty for f in frames) else pd.DataFrame()
        if not h1.empty:
            n = lt.upsert_csv(h1, lt.DATA / "signals_adoption.csv",
                              keys=["rebalance_date", "ticker", "cadence"],
                              sort_by=["cadence", "rebalance_date", "rank"])
            log.info("signals_adoption.csv: %d rows total", n)
        else:
            log.warning("H1 produced no rows — check upstream coverage")

        if args.cadence in ("monthly", "both") and \
                args.h2_source in ("measured", "both"):
            h2 = build_h2(store, monthly_dates(start, end))
            if not h2.empty:
                n = lt.upsert_csv(h2, lt.DATA / "signals_nowcast.csv",
                                  keys=["date", "material"],
                                  sort_by=["date", "material"])
                log.info("signals_nowcast.csv: %d rows total", n)
            else:
                log.warning("measured H2 produced no rows — check coverage")

    if args.h2_source in ("trends", "both"):
        tstore = load_trends_store()
        if tstore is not None:
            h2t = build_h2(tstore, monthly_dates(start, end))
            if not h2t.empty:
                n = lt.upsert_csv(h2t, lt.DATA / "signals_nowcast_trends.csv",
                                  keys=["date", "material"],
                                  sort_by=["date", "material"])
                log.info("signals_nowcast_trends.csv: %d rows total "
                         "(TRENDS PROXY — see DECISIONS.md v1 addendum)", n)
            else:
                log.warning("trends-proxy H2 produced no rows")

    if store is None and args.h2_source == "measured":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
