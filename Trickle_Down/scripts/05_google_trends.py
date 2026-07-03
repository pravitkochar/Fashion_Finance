"""P2 — pull Google Trends monthly interest for material/color terms.

Terms come from config/material_taxonomy.json (each material's trends_terms)
plus Shein proxy terms (Shein is private — Trends is its only downstream
signal, see universe.json). Output: data/trends/trends.csv per the
lib_trickle contract; known_date = observation date.

Values are batch-relative (Google normalizes each <=5-term request to its own
max) — consumers must use per-term z-scores, never cross-term levels.

Resume-safe: terms already covered through the current month are skipped.
Flags: --terms "a,b,c" to override the catalog, --limit N.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import date

import pandas as pd

import lib_trickle as lt

log = lt.get_logger("05_google_trends")

BATCH = 5
SLEEP_RANGE = (10, 20)
SHEIN_TERMS = ["shein", "shein haul"]
TRENDS_CSV = lt.TRENDS / "trends.csv"


def term_catalog() -> list[tuple[str, str, str]]:
    """[(term, term_type, material)] from taxonomy + Shein proxies."""
    out = []
    for mat, spec in lt.load_taxonomy()["materials"].items():
        for term in spec.get("trends_terms", []):
            out.append((term, "material", mat))
    for term in SHEIN_TERMS:
        out.append((term, "proxy", ""))
    return out


def pending_terms(catalog: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    existing = lt.read_csv_or_empty(TRENDS_CSV)
    if existing.empty:
        return catalog
    month_start = date.today().replace(day=1).isoformat()
    latest = (existing.assign(date=existing["date"].astype(str))
              .groupby("term")["date"].max())
    done = set(latest[latest >= month_start].index)
    return [t for t in catalog if t[0] not in done]


def fetch_batch(pytrends, terms: list[str], timeframe: str) -> pd.DataFrame | None:
    """One interest_over_time call; retry once on 429, else None."""
    for attempt in (1, 2):
        try:
            pytrends.build_payload(terms, timeframe=timeframe, geo="")
            df = pytrends.interest_over_time()
            return df if not df.empty else None
        except Exception as e:  # pytrends raises plain ResponseError on 429
            if "429" in str(e) and attempt == 1:
                log.warning("429 on batch %s — backing off 60s", terms)
                time.sleep(60)
                continue
            log.error("batch %s failed: %s — skipping", terms, e)
            return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--terms", default=None,
                    help="comma-separated term override")
    ap.add_argument("--limit", type=int, default=None,
                    help="max number of terms this run")
    args = ap.parse_args()
    lt.ensure_dirs()

    try:
        from pytrends.request import TrendReq
    except ImportError:
        log.error("pytrends not installed — pip install pytrends")
        return 1

    catalog = term_catalog()
    if args.terms:
        known = {t: (tt, m) for t, tt, m in catalog}
        catalog = [(t.strip(), *known.get(t.strip(), ("proxy", "")))
                   for t in args.terms.split(",") if t.strip()]

    todo = pending_terms(catalog)
    if args.limit:
        todo = todo[:args.limit]
    if not todo:
        log.info("all %d terms current through this month — nothing to do",
                 len(catalog))
        return 0
    log.info("fetching %d/%d terms", len(todo), len(catalog))

    meta = {t: (tt, m) for t, tt, m in todo}
    timeframe = f"2015-01-01 {date.today().isoformat()}"
    pytrends = TrendReq(hl="en-US", tz=0)

    fetched = 0
    for i in range(0, len(todo), BATCH):
        batch = [t for t, _, _ in todo[i:i + BATCH]]
        df = fetch_batch(pytrends, batch, timeframe)
        if df is not None:
            rows = []
            for term in batch:
                if term not in df.columns:
                    log.warning("term %r missing from response", term)
                    continue
                tt, mat = meta[term]
                for dt, val in df[term].items():
                    d = pd.Timestamp(dt).date().isoformat()
                    rows.append({"date": d, "term": term, "term_type": tt,
                                 "material": mat, "value": int(val),
                                 "known_date": d})
            if rows:
                n = lt.upsert_csv(pd.DataFrame(rows), TRENDS_CSV,
                                  keys=["date", "term"],
                                  sort_by=["term", "date"])
                fetched += len(batch)
                log.info("batch %d/%d ok — trends.csv now %d rows",
                         i // BATCH + 1, (len(todo) - 1) // BATCH + 1, n)
        if i + BATCH < len(todo):
            time.sleep(random.uniform(*SLEEP_RANGE))

    log.info("done — %d/%d terms fetched this run", fetched, len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
