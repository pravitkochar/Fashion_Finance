"""P1 — scrape Vogue Runway look galleries for the Tier-1 universe.

Per (house, season) from config/universe.json x lt.iter_seasons(2015), fetch
https://www.vogue.com/fashion-shows/{season-slug}/{brand-slug}, extract the
show date and the look-gallery image URLs, and append rows to
data/runway/runway_looks.csv per the lib_trickle contract. Images are NOT
downloaded here (02_tag_gemini.py caches them); we record image_url only.

Look images are pulled from Vogue's embedded page JSON by regexing
assets.vogue.com photo URLs after unescaping, deduped by photo id, capped at
60/show. The first image can occasionally be a hero/editorial shot — accepted
noise, Gemini tags what it sees.

Output:   data/runway/runway_looks.csv
Soft log: data/runway/_missing.csv on (brand, season) miss
Resume:   data/runway/_scrape_progress.json  "brand|season" -> "ok"|"miss"
Hard stop: cumulative 403/429/Cloudflare > 10 (exit 2), per CLAUDE.md.

Flags: --seasons SS2025,FW2025  --brands gucci,prada  --limit N (total looks,
smoke test)  --delay-min/--delay-max.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

import lib_trickle as lt

log = lt.get_logger("01_scrape_runway")

LOOKS_CSV = lt.RUNWAY / "runway_looks.csv"
MISS_CSV = lt.RUNWAY / "_missing.csv"
PROGRESS = lt.RUNWAY / "_scrape_progress.json"

MAX_LOOKS_PER_SHOW = 60
MAX_BLOCK_HITS = 10
TIMEOUT = 25

UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) "
    "Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# universe slug -> ordered slug aliases on vogue.com (parent-repo pattern)
SLUG_ALIASES = {
    "christian-dior": ["christian-dior", "dior"],
    "saint-laurent": ["saint-laurent", "yves-saint-laurent"],
    "burberry": ["burberry", "burberry-prorsum"],
    "moncler": ["moncler", "moncler-gamme-rouge", "moncler-genius"],
    "ralph-lauren": ["ralph-lauren", "ralph-lauren-collection"],
    "zegna": ["zegna", "ermenegildo-zegna"],
    "tods": ["tod-s", "tods"],
    "salvatore-ferragamo": ["salvatore-ferragamo", "ferragamo"],
}


def season_url_slug(season_code: str) -> str:
    s, y = lt.parse_season_code(season_code)
    return f"spring-{y}-ready-to-wear" if s == "SS" else f"fall-{y}-ready-to-wear"


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


def detect_block(status: int, body: str) -> bool:
    if status in (403, 429):
        return True
    sample = body[:4000].lower()
    return "cloudflare" in sample and ("attention required" in sample
                                       or "challenge" in sample)


def extract_show_date(html: str) -> str | None:
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
    for prop in (("meta", {"property": "article:published_time"}),
                 ("meta", {"name": "pubdate"}),
                 ("meta", {"property": "og:article:published_time"})):
        tag = soup.find(*prop)
        if tag and tag.get("content"):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", tag["content"])
            if m:
                return m.group(1)
    return None


_PHOTO_RE = re.compile(r"https://assets\.vogue\.com/photos/[A-Za-z0-9/_,.:%-]+")
_PHOTO_ID_RE = re.compile(r"(https://assets\.vogue\.com/photos/[A-Za-z0-9]+)")


def extract_look_images(html: str) -> list[str]:
    """All gallery photo URLs, deduped by photo id, page order preserved."""
    text = html.replace("\\u002F", "/").replace("\\/", "/")
    seen: set[str] = set()
    out: list[str] = []
    for url in _PHOTO_RE.findall(text):
        m = _PHOTO_ID_RE.match(url)
        if not m:
            continue
        photo_id = m.group(1)
        if photo_id in seen:
            continue
        seen.add(photo_id)
        out.append(url)
        if len(out) >= MAX_LOOKS_PER_SHOW:
            break
    return out


def append_miss(brand: str, season: str, first_url: str, reason: str) -> None:
    row = pd.DataFrame([{"brand_slug": brand, "season_code": season,
                         "first_url": first_url, "reason": reason,
                         "logged": date.today().isoformat()}])
    header = not MISS_CSV.exists()
    row.to_csv(MISS_CSV, mode="a", header=header, index=False)


def flush_rows(rows: list[dict]) -> None:
    if not rows:
        return
    n = lt.upsert_csv(pd.DataFrame(rows), LOOKS_CSV, keys=["look_id"],
                      sort_by=["brand_slug", "season_code", "look_id"])
    log.info("runway_looks.csv now %d rows (+%d this flush)", n, len(rows))
    rows.clear()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="",
                    help="comma list e.g. SS2025,FW2025 (default: all known)")
    ap.add_argument("--brands", default="", help="comma list of universe slugs")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N total looks this run (smoke test)")
    ap.add_argument("--delay-min", type=float, default=1.5)
    ap.add_argument("--delay-max", type=float, default=3.0)
    args = ap.parse_args()

    lt.ensure_dirs()
    houses = lt.load_universe()["tier1_runway"]
    if args.brands:
        keep = {b.strip() for b in args.brands.split(",") if b.strip()}
        houses = [h for h in houses if h["slug"] in keep]
    seasons = ([s.strip() for s in args.seasons.split(",") if s.strip()]
               if args.seasons else lt.iter_seasons(2015))
    for s in seasons:
        lt.parse_season_code(s)  # validate early

    progress = lt.load_progress(PROGRESS)
    log.info("resume: %d (brand,season) keys done; %d houses x %d seasons queued",
             len(progress), len(houses), len(seasons))

    session = requests.Session()
    block_hits = 0
    looks_this_run = 0
    rows: list[dict] = []
    today = date.today().isoformat()

    tasks = [(h, s) for h in houses for s in seasons]
    for house, season_code in tqdm(tasks, desc="runway scrape"):
        slug = house["slug"]
        pkey = f"{slug}|{season_code}"
        if pkey in progress:
            continue
        if args.limit and looks_this_run >= args.limit:
            log.info("--limit %d reached, stopping run", args.limit)
            break

        aliases = SLUG_ALIASES.get(slug, [slug])
        outcome, first_url = "miss", None
        for alias in aliases:
            url = f"https://www.vogue.com/fashion-shows/{season_url_slug(season_code)}/{alias}"
            first_url = first_url or url
            status, body = fetch(url, session)
            time.sleep(random.uniform(args.delay_min, args.delay_max))

            if detect_block(status, body):
                block_hits += 1
                log.error("block detected (%s, total=%d) on %s", status, block_hits, url)
                if block_hits > MAX_BLOCK_HITS:
                    log.error("HARD STOP: >%d block hits", MAX_BLOCK_HITS)
                    flush_rows(rows)
                    lt.save_progress(progress, PROGRESS)
                    return 2
                continue
            if status in (404, 410) or status != 200 or not body:
                continue

            show_date = extract_show_date(body)
            images = extract_look_images(body)
            if not show_date or not images:
                append_miss(slug, season_code, url,
                            "no show date" if not show_date else "no gallery images")
                continue

            for i, img in enumerate(images, start=1):
                rows.append({
                    "look_id": f"{slug}|{season_code}|{i:03d}",
                    "brand_slug": slug,
                    "parent_ticker": house.get("parent_ticker") or "",
                    "city": house.get("city", ""),
                    "season_code": season_code,
                    "show_date": show_date,
                    "image_url": img,
                    "source_url": url,
                    "scraped_at": today,
                })
            looks_this_run += len(images)
            outcome = "ok"
            break

        if outcome == "miss":
            append_miss(slug, season_code, first_url or "", "no alias 200/parseable")
        progress[pkey] = outcome

        if len(rows) >= 300:
            flush_rows(rows)
            lt.save_progress(progress, PROGRESS)

    flush_rows(rows)
    lt.save_progress(progress, PROGRESS)

    done = lt.read_csv_or_empty(LOOKS_CSV)
    n_shows = done.groupby(["brand_slug", "season_code"]).ngroups if not done.empty else 0
    log.info("run complete: +%d looks this run; %d total looks, %d shows, %d blocks",
             looks_this_run, len(done), n_shows, block_hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
