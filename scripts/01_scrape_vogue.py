"""Phase 1 — scrape Vogue Runway show dates for SS/FW main runway, 2000-2025.

Per (brand_key, year, season), try a list of slug aliases until one returns 200
with a parseable date. Brand keys map to tickers via the universe table.

Output: data/show_dates.csv  [brand_slug, ticker, season, year, show_date, designer, source_url]
Soft log: data/missing_shows.csv on miss
Resume: data/scrape_progress.json maps "brand_key|year|season" -> "ok"|"miss"

Hard stops:
  - cumulative HTTP 403/429/Cloudflare > 10
  - <400 successful rows after full run
  - >1 of 5 sanity-check dates fall outside expected month windows
"""
from __future__ import annotations

import csv
import json
import logging
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("phase1")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_CSV = DATA / "show_dates.csv"
MISS_CSV = DATA / "missing_shows.csv"
PROGRESS = DATA / "scrape_progress.json"

UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# brand_key -> (ticker_or_split, list of slug aliases tried in order)
BRAND_TABLE = {
    "louis-vuitton":      ("MC.PA",        ["louis-vuitton"]),
    "dior":               ("MC.PA",        ["christian-dior", "dior"]),
    "gucci":              ("KER.PA",       ["gucci"]),
    "saint-laurent":      ("KER.PA",       ["saint-laurent", "yves-saint-laurent"]),
    "bottega-veneta":     ("KER.PA",       ["bottega-veneta"]),
    "michael-kors":       ("CPRI",         ["michael-kors-collection", "michael-kors"]),
    "versace":            ("CPRI",         ["versace", "atelier-versace"]),
    "coach":              ("COH_OR_TPR",   ["coach", "coach-1941"]),
    "calvin-klein":       ("PVH",          ["calvin-klein", "calvin-klein-collection", "calvin-klein-205w39nyc"]),
    "tommy-hilfiger":     ("PVH",          ["tommy-hilfiger"]),
    "hermes":             ("RMS.PA",       ["hermes"]),
    "burberry":           ("BRBY.L",       ["burberry-prorsum", "burberry"]),
    "prada":              ("1913.HK",      ["prada"]),
    "miu-miu":            ("1913.HK",      ["miu-miu"]),
    "brunello-cucinelli": ("BC.MI",        ["brunello-cucinelli"]),
    "moncler":            ("MONC.MI",      ["moncler-gamme-rouge", "moncler-genius", "moncler"]),
    "hugo-boss":          ("BOSS.DE",      ["hugo-boss", "boss"]),
    "ralph-lauren":       ("RL",           ["ralph-lauren", "ralph-lauren-collection"]),
    "salvatore-ferragamo":("SFER.MI",      ["salvatore-ferragamo", "ferragamo"]),
    "tods":               ("TOD.MI",       ["tod-s", "tods"]),
}

YEARS = list(range(2000, 2026))
SEASONS = ["spring", "fall"]

REQUEST_DELAY_SEC = 0.8
MAX_BLOCK_HITS = 10
TIMEOUT = 25

EXPECTED_MONTHS = {"spring": {8, 9, 10}, "fall": {1, 2, 3, 4}}


def resolve_ticker(brand_key: str, show_date: str) -> Optional[str]:
    base, _ = BRAND_TABLE[brand_key]
    if base == "COH_OR_TPR":
        return "COH" if show_date < "2017-10-31" else "TPR"
    if brand_key == "versace" and show_date < "2019-01-01":
        return None
    if brand_key == "michael-kors" and show_date < "2011-12-15":
        return None
    return base


def load_progress() -> dict:
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text())
        except Exception:
            return {}
    return {}


def save_progress(d: dict) -> None:
    PROGRESS.write_text(json.dumps(d, indent=0))


def append_csv(path: Path, header: list[str], row: list) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def fetch(url: str, session: requests.Session) -> tuple[int, str]:
    headers = {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        return r.status_code, r.text
    except requests.RequestException as e:
        log.warning("request error %s: %s", url, e)
        return -1, ""


def extract_show_date(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("datePublished", "dateCreated", "dateModified"):
                v = item.get(key)
                if isinstance(v, str):
                    m = re.match(r"(\d{4}-\d{2}-\d{2})", v)
                    if m:
                        return m.group(1)
    for prop in (
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"property": "og:article:published_time"}),
    ):
        tag = soup.find(*prop)
        if tag and tag.get("content"):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", tag["content"])
            if m:
                return m.group(1)
    return None


def extract_designer(html: str) -> Optional[str]:
    """Best-effort designer extraction from page text. Returns string or None."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    m = re.search(r"creative director[: ]+([A-Z][a-zA-Z\.\-' ]{2,40})", text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"designed by\s+([A-Z][a-zA-Z\.\-' ]{2,40})", text, re.I)
    if m:
        return m.group(1).strip()
    return None


def detect_block(status: int, body: str) -> bool:
    if status in (403, 429):
        return True
    sample = body[:4000].lower()
    if "cloudflare" in sample and ("attention required" in sample or "challenge" in sample):
        return True
    return False


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    progress = load_progress()
    log.info("resume: %d (brand,year,season) keys already attempted", len(progress))

    session = requests.Session()
    block_hits = 0
    new_success = 0
    new_miss = 0

    tasks: list[tuple[str, int, str]] = []
    for bk in BRAND_TABLE:
        for year in YEARS:
            for season in SEASONS:
                tasks.append((bk, year, season))

    pbar = tqdm(tasks, desc="vogue scrape")
    for brand_key, year, season in pbar:
        pkey = f"{brand_key}|{year}|{season}"
        if pkey in progress:
            continue

        _, aliases = BRAND_TABLE[brand_key]
        outcome = "miss"
        first_url = None

        for alias in aliases:
            url = f"https://www.vogue.com/fashion-shows/{season}-{year}-ready-to-wear/{alias}"
            if first_url is None:
                first_url = url
            status, body = fetch(url, session)
            time.sleep(REQUEST_DELAY_SEC)

            if detect_block(status, body):
                block_hits += 1
                log.error("block detected (%s, total=%d) on %s", status, block_hits, url)
                if block_hits > MAX_BLOCK_HITS:
                    log.error("HARD STOP: >%d block hits", MAX_BLOCK_HITS)
                    save_progress(progress)
                    sys.exit(2)
                continue

            if status in (404, 410):
                continue
            if status != 200 or not body:
                continue

            show_date = extract_show_date(body)
            if not show_date:
                continue

            ticker = resolve_ticker(brand_key, show_date)
            if ticker is None:
                outcome = "drop_pre_listing"
                break

            designer = extract_designer(body) or ""
            append_csv(
                OUT_CSV,
                ["brand_slug", "ticker", "season", "year", "show_date", "designer", "source_url"],
                [brand_key, ticker, season, year, show_date, designer, url],
            )
            outcome = "ok"
            new_success += 1
            break

        if outcome == "miss":
            append_csv(MISS_CSV, ["brand_key", "year", "season", "first_url", "reason"],
                       [brand_key, year, season, first_url, "no alias 200/parseable"])
            new_miss += 1

        progress[pkey] = outcome

        if (new_success + new_miss) % 25 == 0:
            save_progress(progress)
            pbar.set_postfix(ok=new_success, miss=new_miss, blocks=block_hits)

    save_progress(progress)
    log.info("scrape pass complete: +%d ok, +%d miss, %d blocks", new_success, new_miss, block_hits)

    if not OUT_CSV.exists():
        log.error("HARD STOP: no show_dates.csv produced")
        sys.exit(2)

    import pandas as pd

    df = pd.read_csv(OUT_CSV)
    n = len(df)
    log.info("show_dates.csv rows: %d", n)
    if n < 400:
        log.error("HARD STOP: only %d rows (<400)", n)
        sys.exit(2)

    sample = df.sample(min(5, n), random_state=42)
    bad = 0
    for _, r in sample.iterrows():
        try:
            dt = datetime.fromisoformat(r["show_date"])
        except Exception:
            bad += 1
            continue
        if dt.month not in EXPECTED_MONTHS[r["season"]]:
            log.warning("sanity check fail: %s %s %s -> %s",
                        r["brand_slug"], r["season"], r["year"], r["show_date"])
            bad += 1
        else:
            log.info("sanity ok: %s %s %s -> %s",
                     r["brand_slug"], r["season"], r["year"], r["show_date"])
    if bad > 1:
        log.error("HARD STOP: %d/5 sanity fails", bad)
        sys.exit(2)

    log.info("Phase 1 complete. Rows=%d", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
