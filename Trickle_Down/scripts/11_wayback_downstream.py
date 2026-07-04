"""P1 (V2) — reconstruct historical retailer material mix from the Wayback
Machine.

For each (retailer, month): CDX-list archived product pages, fetch a sample
of snapshots (original bytes via the id_ endpoint), extract the fabric
composition from visible text, and emit downstream_items/downstream_tags
rows with source="wayback" and first_seen = the SNAPSHOT date — point-in-time
by construction (DECISIONS.md 2026-07-03 V2 entry).

item_id is month-scoped (retailer|url|YYYY-MM): the same garment archived in
two months counts in both months' assortment sample, which is the intended
"what was on offer that month" measure.

Politeness: ~1 request / 2s against web.archive.org, full resume via
data/downstream/_wayback_progress.json, --max-requests budget so the daily
job can chip away at the sweep.

Flags: --retailers zara,hm,asos  --start 2017-01 --end 2025-12
       --pages-per-month 40  --max-requests 1200  --months 2019-03,2019-04
Output coverage report: data/wayback_coverage.csv
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from datetime import date

import pandas as pd
import requests

import lib_trickle as lt

log = lt.get_logger("11_wayback")

ITEMS_CSV = lt.DOWNSTREAM / "downstream_items.csv"
TAGS_CSV = lt.DOWNSTREAM / "downstream_tags.csv"
PROGRESS = lt.DOWNSTREAM / "_wayback_progress.json"
COVERAGE = lt.DATA / "wayback_coverage.csv"

CDX = "https://web.archive.org/cdx/search/cdx"
SNAP = "https://web.archive.org/web/{ts}id_/{url}"
UA = {"User-Agent": "trickle-down-research/1.0 (personal quant research; "
                    "contact pravitkochar@gmail.com)"}
PAUSE = (1.8, 3.0)
CDX_PAUSE = (4.0, 7.0)      # CDX index is far more throttle-sensitive
COOLOFF = 90                # seconds after a throttle/refusal

# retailer -> LIST of archive eras (cdx prefix, product-url regex as CDX
# full-match, month clamp). Eras are where composition is actually in the
# archived bytes (all probed 2026-07-03): Zara only pre-SPA; H&M legacy
# domain 2014-2018 then www2; ASOS throughout; Uniqlo's coded .html era.
SOURCES = {
    "zara": [{"prefix": "www.zara.com/us/en/",
              "filter": r".*(/product/\d+|-p\d{6,}\.html)",
              "from": "2016-01", "to": "2017-12"}],
    "hm":   [{"prefix": "www.hm.com/us/product",
              "filter": r".*/product/\d+.*",
              "from": "2014-01", "to": "2018-06"},
             {"prefix": "www2.hm.com/en_us/productpage",
              "filter": r".*productpage\.\d+\.html.*",
              "from": "2018-01", "to": "2026-12"}],
    "asos": [{"prefix": "www.asos.com/us/",
              "filter": r".*/prd/\d+.*",
              "from": "2016-01", "to": "2026-12"}],
    "uniqlo": [{"prefix": "www.uniqlo.com/us/en/",
                "filter": r".*-\d{6}\.html",
                "from": "2016-01", "to": "2021-12"}],
}
TICKERS = {"zara": "ITX.MC", "hm": "HM-B.ST", "asos": "ASC.L",
           "uniqlo": "9983.T"}

# H&M keeps composition inside script-block JSON — read from RAW html before
# script-stripping. Two vintages: www2 era 'compositions': ['Linen 100%'];
# legacy era "composition":"100% cotton".
HM_COMP_RE = re.compile(r"'compositions'\s*:\s*\[([^\]]*)\]")
HM_LEGACY_RE = re.compile(r'"composition"\s*:\s*"([^"]{3,80})"')


def extract_hm(html: str) -> str:
    m = HM_COMP_RE.search(html)
    if m:
        parts = re.findall(r"'([^']{3,60})'", m.group(1))
        return ", ".join(parts[:6])
    hits = HM_LEGACY_RE.findall(html)
    seen, keep = set(), []
    for h in hits:
        if h.lower() not in seen:
            seen.add(h.lower())
            keep.append(h)
        if len(keep) >= 6:
            break
    return ", ".join(keep)


RAW_EXTRACTORS = {"hm": extract_hm}

STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
PCT_NAME = re.compile(r"(\d{1,3})\s*%\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ \-]{2,28})")
NAME_PCT = re.compile(r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ \-]{2,28}?)\s+(\d{1,3})\s*%")
DENIM_RE = re.compile(r"\b(denim|jeans?)\b", re.I)


def pause() -> None:
    time.sleep(random.uniform(*PAUSE))


def extract_composition(html: str) -> str:
    """Fiber pairs from VISIBLE text only; a pair counts only when the name
    maps into the taxonomy, which kills CSS '100%' noise."""
    text = TAG_RE.sub(" ", STYLE_RE.sub(" ", html))
    kept, seen = [], set()
    hits = [(p, n) for p, n in PCT_NAME.findall(text)]
    hits += [(p, n) for n, p in NAME_PCT.findall(text)]
    for pct, name in hits:
        canon = lt.normalize_material(name)
        if not canon or not (0 < int(pct) <= 100):
            continue
        if canon not in seen:
            seen.add(canon)
            kept.append(f"{pct}% {canon}")
        if len(kept) >= 6:
            break
    return ", ".join(kept)


def extract_title(html: str, retailer: str) -> str:
    m = TITLE_RE.search(html)
    if not m:
        return ""
    t = TAG_RE.sub(" ", m.group(1))
    t = re.split(r"\s*[|–-]\s*(ZARA|H&M|ASOS)", t)[0]
    return re.sub(r"\s+", " ", t).strip()[:120]


def cdx_month(prefix: str, url_filter: str, month: str,
              limit: int) -> list[tuple[str, str]]:
    ym = month.replace("-", "")
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            r = requests.get(CDX, params={
                "url": prefix, "matchType": "prefix",
                "from": ym, "to": ym,
                "filter": ["statuscode:200", f"original:{url_filter}"],
                "collapse": "urlkey", "fl": "timestamp,original",
                "limit": str(limit * 3)}, headers=UA, timeout=60)
            r.raise_for_status()
            rows = [ln.split(" ", 1) for ln in r.text.strip().splitlines()
                    if " " in ln]
            random.Random(month).shuffle(rows)   # deterministic sample
            time.sleep(random.uniform(*CDX_PAUSE))
            return [(ts, url) for ts, url in rows[:limit]]
        except requests.RequestException as e:
            last_err = e
            if attempt == 1:
                log.info("CDX throttled (%s) — cooling off %ds",
                         type(e).__name__, COOLOFF)
                time.sleep(COOLOFF)
    raise last_err


def fetch_snapshot(ts: str, url: str) -> str | None:
    for attempt in (1, 2):
        try:
            r = requests.get(SNAP.format(ts=ts, url=url), headers=UA,
                             timeout=45)
            if r.status_code == 200 and r.text:
                return r.text
            return None
        except requests.ConnectionError:
            if attempt == 1:
                time.sleep(30)                   # transient refusal
        except requests.RequestException as e:
            log.debug("snapshot fail %s: %s", url[:60], e)
            return None
    return None


def persist(items: list[dict], tags: list[dict]) -> None:
    if items:
        lt.upsert_csv(pd.DataFrame(items), ITEMS_CSV, keys=["item_id"],
                      sort_by=["retailer", "first_seen"])
    if tags:
        df_new = pd.DataFrame(tags)
        old = lt.read_csv_or_empty(TAGS_CSV, ["item_id", "material", "share"])
        touched = set(df_new["item_id"])
        kept = old[~old["item_id"].isin(touched)] if not old.empty else old
        merged = pd.concat([kept, df_new], ignore_index=True)
        tmp = TAGS_CSV.with_suffix(".tmp")
        merged.to_csv(tmp, index=False)
        tmp.replace(TAGS_CSV)


def month_range(start: str, end: str) -> list[str]:
    return [str(p) for p in pd.period_range(start, end, freq="M")]


def process_month(retailer: str, month: str, pages: int,
                  budget: dict) -> dict:
    eras = [e for e in SOURCES[retailer] if e["from"] <= month <= e["to"]]
    if not eras:
        return {"status": "ok", "n_pages": 0, "n_comp": 0,
                "note": "outside retailer era clamp"}
    snaps = []
    per_era = max(1, pages // len(eras))
    for era in eras:
        try:
            snaps += cdx_month(era["prefix"], era["filter"], month, per_era)
        except requests.RequestException as e:
            log.warning("[%s %s] CDX error: %s", retailer, month,
                        str(e)[:120])
            return {"status": "cdx_error", "n_pages": 0, "n_comp": 0}
        budget["used"] += 1

    # fetch in a small pool — latency overlaps, per-worker pacing keeps the
    # aggregate rate polite (~2-3 req/s across 4 connections); parsing and
    # all file writes stay in this thread
    remaining = max(0, budget["max"] - budget["used"])
    snaps = snaps[:remaining]
    budget["used"] += len(snaps)

    def _fetch(tsurl):
        ts, url = tsurl
        html = fetch_snapshot(ts, url)
        time.sleep(random.uniform(0.8, 1.4))
        return ts, url, html

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(_fetch, snaps))

    items, tags = [], []
    n_comp = 0
    for ts, url, html in fetched:
        if not html:
            continue
        comp = (RAW_EXTRACTORS.get(retailer, lambda h: "")(html)
                or extract_composition(html))
        name = extract_title(html, retailer)
        snap_date = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
        category = "denim" if DENIM_RE.search(name + " " + url) else "archive"
        item_id = lt.stable_id(retailer, url, month)
        items.append({"item_id": item_id, "retailer": retailer,
                      "ticker": TICKERS[retailer], "product_name": name,
                      "category": category, "url": url,
                      "first_seen": snap_date, "composition_raw": comp,
                      "price": None, "currency": "", "source": "wayback"})
        if comp:
            n_comp += 1
            shares = lt.parse_composition(comp)
            if category == "denim" and "cotton" in shares:
                shares["denim"] = shares.get("denim", 0) + shares.pop("cotton")
            tags.extend({"item_id": item_id, "material": m, "share": s}
                        for m, s in shares.items())
    persist(items, tags)
    done = budget["used"] < budget["max"]
    return {"status": "ok" if done else "partial",
            "n_pages": len(items), "n_comp": n_comp}


def write_coverage() -> None:
    items = lt.read_csv_or_empty(ITEMS_CSV)
    if items.empty:
        return
    wb = items[items["source"] == "wayback"].copy()
    if wb.empty:
        return
    tags = lt.read_csv_or_empty(TAGS_CSV, ["item_id", "material", "share"])
    tagged = set(tags["item_id"]) if not tags.empty else set()
    wb["month"] = wb["first_seen"].astype(str).str.slice(0, 7)
    wb["has_comp"] = wb["item_id"].isin(tagged)
    cov = (wb.groupby(["retailer", "month"])
           .agg(n_items=("item_id", "count"), n_comp=("has_comp", "sum"))
           .reset_index())
    cov.to_csv(COVERAGE, index=False)
    ok = cov[cov["n_comp"] >= 30].groupby("retailer")["month"].count()
    log.info("coverage: %d retailer-months sampled; months with n_comp>=30: %s",
             len(cov), ok.to_dict())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--retailers", default=",".join(SOURCES))
    ap.add_argument("--start", default="2016-01")
    ap.add_argument("--end", default="2025-12")
    ap.add_argument("--months", default="", help="explicit list, overrides range")
    ap.add_argument("--pages-per-month", type=int, default=40)
    ap.add_argument("--max-requests", type=int, default=1200)
    args = ap.parse_args()
    lt.ensure_dirs()

    months = ([m.strip() for m in args.months.split(",") if m.strip()]
              if args.months else month_range(args.start, args.end))
    retailers = [r.strip() for r in args.retailers.split(",")
                 if r.strip() in SOURCES]
    progress = lt.load_progress(PROGRESS)
    budget = {"used": 0, "max": args.max_requests}

    for month in months:                    # month-major: coverage grows evenly
        for retailer in retailers:
            key = f"{retailer}|{month}"
            rec = progress.get(key, {})
            in_era = any(e["from"] <= month <= e["to"]
                         for e in SOURCES[retailer])
            # clamp-skipped cells get retried once their era opens up
            if rec.get("status") == "ok" and not (
                    rec.get("note") == "outside retailer era clamp"
                    and in_era):
                continue
            if budget["used"] >= budget["max"]:
                log.info("request budget exhausted (%d) — resuming next run",
                         budget["max"])
                lt.save_progress(progress, PROGRESS)
                write_coverage()
                return 0
            res = process_month(retailer, month, args.pages_per_month, budget)
            progress[key] = res | {"run": date.today().isoformat()}
            log.info("[%s %s] %s: %d pages, %d with composition",
                     retailer, month, res["status"], res["n_pages"],
                     res["n_comp"])
            lt.save_progress(progress, PROGRESS)
    write_coverage()
    log.info("sweep complete for requested range")
    return 0


if __name__ == "__main__":
    sys.exit(main())
