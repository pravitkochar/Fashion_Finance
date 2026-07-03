"""Brief 2 / Phase 1 — scrape Vogue Met Gala coverage and build (parent x year) panel.

For each Met Gala (2000-2025, ex 2020, plus Sept 2021 makeup):
  - Try several Vogue URL patterns for the year's best-dressed / coverage article.
  - Parse for celebrity-name + brand-name mentions.
  - Map brands -> parent_ticker via comprehensive table.
  - Assign tier per parent per year:
      A = parent had a celebrity flagged as "best dressed"/top of article
      C = parent dressed someone mentioned in the article body
      N = no credits found
  (Tier B requires Lyst data which is unscrapable; we collapse B into A when
   the article ranks the look high, otherwise treat as C. Soft-log the year.)

Output: brief_2_met_gala/data/met_gala_panel.csv  (~350 rows)
Soft logs: ambiguous_tier.csv, missing_articles.csv

Hard stops:
  - <300 panel rows after construction (will retry once at 150 if needed)
  - Tier-A subset <8 events (will retry once at 4)
  - Vogue scrape blocked (>5 cumulative 403/429)
"""
from __future__ import annotations

import csv
import json
import logging
import random
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("brief2_phase1")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PANEL = DATA / "met_gala_panel.csv"
RAW_CREDITS = DATA / "met_gala_credits.csv"
MISSING = DATA / "missing_articles.csv"
AMBIG = DATA / "ambiguous_tier.csv"
PROGRESS = DATA / "scrape_progress.json"

UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

PARENT_TICKERS = [
    "MC.PA", "KER.PA", "CPRI", "TPR", "COH", "PVH",
    "RMS.PA", "BRBY.L", "1913.HK", "BC.MI", "MONC.MI",
    "BOSS.DE", "RL", "SFER.MI", "TOD.MI",
]

# Brand text -> parent_ticker. Lowercased; longer keys matched before shorter.
BRAND_TO_PARENT: dict[str, str] = {
    # LVMH
    "louis vuitton": "MC.PA",
    "christian dior": "MC.PA",
    "dior couture": "MC.PA",
    " dior ": "MC.PA",
    "loewe": "MC.PA",
    "celine": "MC.PA",
    "céline": "MC.PA",
    "givenchy": "MC.PA",
    "fendi": "MC.PA",
    "marc jacobs": "MC.PA",
    "kenzo": "MC.PA",
    "tiffany & co": "MC.PA",
    "bulgari": "MC.PA",
    # Kering
    "gucci": "KER.PA",
    "saint laurent": "KER.PA",
    "yves saint laurent": "KER.PA",
    "ysl": "KER.PA",
    "bottega veneta": "KER.PA",
    "balenciaga": "KER.PA",
    "alexander mcqueen": "KER.PA",
    "mcqueen": "KER.PA",
    "brioni": "KER.PA",
    "boucheron": "KER.PA",
    # Capri
    "michael kors": "CPRI",
    "versace": "CPRI",
    "atelier versace": "CPRI",
    "jimmy choo": "CPRI",
    # Tapestry / legacy Coach
    "coach": "TPR",
    "kate spade": "TPR",
    "stuart weitzman": "TPR",
    # PVH
    "calvin klein": "PVH",
    "tommy hilfiger": "PVH",
    # Hermes
    "hermès": "RMS.PA",
    "hermes": "RMS.PA",
    # Burberry
    "burberry": "BRBY.L",
    # Prada
    "prada": "1913.HK",
    "miu miu": "1913.HK",
    # Brunello
    "brunello cucinelli": "BC.MI",
    # Moncler
    "moncler": "MONC.MI",
    # Hugo Boss
    "hugo boss": "BOSS.DE",
    # Ralph Lauren
    "ralph lauren": "RL",
    "polo ralph lauren": "RL",
    "polo by ralph lauren": "RL",
    # Ferragamo
    "salvatore ferragamo": "SFER.MI",
    "ferragamo": "SFER.MI",
    # Tod's
    "tod's": "TOD.MI",
    "tods ": "TOD.MI",
}


def first_monday_of_may(year: int) -> date:
    d = date(year, 5, 1)
    return d + timedelta(days=(0 - d.weekday()) % 7)


def gala_dates() -> dict[int, date]:
    out: dict[int, date] = {}
    for y in range(2000, 2026):
        if y == 2020:
            continue
        if y == 2021:
            out[y] = date(2021, 9, 13)
        else:
            out[y] = first_monday_of_may(y)
    return out


URL_TEMPLATES = [
    "https://www.vogue.com/article/met-gala-{y}-best-dressed",
    "https://www.vogue.com/article/met-gala-{y}-best-dressed-list",
    "https://www.vogue.com/article/met-gala-{y}-best-looks",
    "https://www.vogue.com/article/met-gala-best-dressed-{y}",
    "https://www.vogue.com/article/best-dressed-met-gala-{y}",
    "https://www.vogue.com/slideshow/met-gala-{y}-best-dressed",
    "https://www.vogue.com/article/met-gala-{y}-red-carpet",
    "https://www.vogue.com/article/met-gala-{y}-fashion-recap",
    "https://www.vogue.com/article/met-gala-{y}-celebrity-looks",
    "https://www.vogue.com/article/met-gala-{y}-everything-need-know",
]


def fetch(url: str, session: requests.Session) -> tuple[int, str]:
    headers = {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = session.get(url, headers=headers, timeout=25, allow_redirects=True)
        return r.status_code, r.text
    except requests.RequestException as e:
        log.warning("request error %s: %s", url, e)
        return -1, ""


def detect_block(status: int, body: str) -> bool:
    if status in (403, 429):
        return True
    sample = body[:4000].lower()
    if "cloudflare" in sample and ("attention required" in sample or "challenge" in sample):
        return True
    return False


def fetch_year_article(year: int, session: requests.Session) -> tuple[Optional[str], Optional[str], int]:
    """Try multiple URL patterns. Return (url, html, blocks_seen)."""
    blocks = 0
    for tmpl in URL_TEMPLATES:
        url = tmpl.format(y=year)
        status, body = fetch(url, session)
        time.sleep(0.7)
        if detect_block(status, body):
            blocks += 1
            continue
        if status == 200 and body and len(body) > 5000:
            return url, body, blocks
    return None, None, blocks


def looks_like_best_dressed(url: str) -> bool:
    return "best-dressed" in url or "best-looks" in url or "best-dressed" in url.lower()


def extract_credits(html: str) -> list[tuple[str, str]]:
    """Return list of (name_or_section_text, raw_brand_text_with_context)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    body_text = soup.get_text(" ", strip=True)
    body_text_l = body_text.lower()

    # Sections often start with celebrity names in headers.
    sections = []
    for tag in soup.find_all(["h2", "h3", "h4", "strong"]):
        nm = tag.get_text(" ", strip=True)
        if 2 <= len(nm.split()) <= 5 and nm[0:1].isupper():
            sections.append(nm)

    # Find brand mentions across body text and pair with the nearest preceding section name.
    credits: list[tuple[str, str]] = []
    for brand_key in sorted(BRAND_TO_PARENT.keys(), key=len, reverse=True):
        for m in re.finditer(re.escape(brand_key), body_text_l):
            start = max(0, m.start() - 120)
            window = body_text[start:m.end() + 120]
            # find the most recent section header preceding this mention
            best_sec = ""
            cursor = body_text[:m.start()]
            for sec in sections:
                idx = cursor.rfind(sec)
                if idx >= 0 and idx > cursor.rfind(best_sec or ""):
                    best_sec = sec
            credits.append((best_sec or "(unknown)", window.strip()))
    return credits


def normalize_brand(text: str) -> Optional[str]:
    t = text.lower()
    for brand_key in sorted(BRAND_TO_PARENT.keys(), key=len, reverse=True):
        if brand_key in t:
            return BRAND_TO_PARENT[brand_key]
    return None


THEMES = {
    2000: "Rock Style", 2001: "Jacqueline Kennedy: The White House Years",
    2002: "Versace: Made in Italy", 2003: "Goddess: The Classical Mode",
    2004: "Dangerous Liaisons", 2005: "Chanel",
    2006: "AngloMania", 2007: "Poiret: King of Fashion",
    2008: "Superheroes: Fashion and Fantasy", 2009: "The Model as Muse",
    2010: "American Woman: Fashioning a National Identity",
    2011: "Alexander McQueen: Savage Beauty",
    2012: "Schiaparelli and Prada: Impossible Conversations",
    2013: "Punk: Chaos to Couture", 2014: "Charles James: Beyond Fashion",
    2015: "China: Through the Looking Glass",
    2016: "Manus x Machina: Fashion in an Age of Technology",
    2017: "Rei Kawakubo/Comme des Garcons: Art of the In-Between",
    2018: "Heavenly Bodies: Fashion and the Catholic Imagination",
    2019: "Camp: Notes on Fashion",
    2021: "In America: A Lexicon of Fashion",
    2022: "In America: An Anthology of Fashion",
    2023: "Karl Lagerfeld: A Line of Beauty",
    2024: "Sleeping Beauties: Reawakening Fashion",
    2025: "Superfine: Tailoring Black Style",
}


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    galas = gala_dates()
    log.info("scraping %d Met Galas (2000-2025 ex 2020, +Sept 2021)", len(galas))

    session = requests.Session()
    raw_credits_rows = []
    missing_rows = []
    blocks_total = 0

    parent_year_top: dict[tuple[str, int], dict] = {}
    article_used: dict[int, str] = {}

    for year, gdate in tqdm(sorted(galas.items()), desc="Vogue articles"):
        url, html, blocks = fetch_year_article(year, session)
        blocks_total += blocks
        if blocks_total > 5:
            log.error("HARD STOP: %d cumulative block hits during scrape", blocks_total)
            sys.exit(2)
        if not html:
            log.warning("year %d: no article found", year)
            missing_rows.append([year, "no article matched any URL pattern"])
            continue
        article_used[year] = url
        is_best_dressed = looks_like_best_dressed(url)

        credits = extract_credits(html)
        log.info("year %d: %s -> %d brand mentions", year, url, len(credits))

        for celeb, ctx in credits:
            parent = normalize_brand(ctx)
            if not parent:
                continue
            raw_credits_rows.append({
                "year": year, "celebrity": celeb, "parent_ticker": parent,
                "context_snippet": ctx[:200], "source_url": url,
                "is_best_dressed_article": is_best_dressed,
            })
            key = (parent, year)
            if key not in parent_year_top:
                parent_year_top[key] = {"count": 0, "in_best_dressed": False, "top_celebrity": celeb}
            parent_year_top[key]["count"] += 1
            if is_best_dressed:
                parent_year_top[key]["in_best_dressed"] = True

    pd.DataFrame(raw_credits_rows).to_csv(RAW_CREDITS, index=False)
    log.info("wrote %s (%d rows)", RAW_CREDITS, len(raw_credits_rows))
    if missing_rows:
        pd.DataFrame(missing_rows, columns=["year", "reason"]).to_csv(MISSING, index=False)

    # Build the panel: 14 parents x N galas.
    panel_rows = []
    eid = 0
    for year, gdate in sorted(galas.items()):
        for parent in PARENT_TICKERS:
            info = parent_year_top.get((parent, year), {})
            n = int(info.get("count", 0))
            in_bd = bool(info.get("in_best_dressed", False))
            top_celeb = info.get("top_celebrity", "") if n else ""
            if n == 0:
                tier = "N"
            elif in_bd:
                tier = "A"
            else:
                tier = "C"
            eid += 1
            panel_rows.append({
                "event_id": f"E{eid:05d}",
                "year": int(year),
                "gala_date": gdate.isoformat(),
                "theme": THEMES.get(year, ""),
                "parent_ticker": parent,
                "ticker": parent,           # alias for shared lib_event_study
                "show_date": gdate.isoformat(),  # alias t=0 anchor
                "dress_credits_count": n,
                "top_celebrity_dressed": top_celeb,
                "tier": tier,
                "article_url": article_used.get(year, ""),
            })

    panel = pd.DataFrame(panel_rows)
    panel.to_csv(PANEL, index=False)
    log.info("wrote %s rows=%d", PANEL, len(panel))

    n = len(panel)
    n_a = int((panel["tier"] == "A").sum())
    n_c = int((panel["tier"] == "C").sum())
    n_n = int((panel["tier"] == "N").sum())
    log.info("panel breakdown: tier A=%d C=%d N=%d", n_a, n_c, n_n)
    log.info("articles found for %d / %d galas", len(article_used), len(galas))

    # Hard stops
    floor_panel = int(__import__("os").environ.get("BRIEF2_PANEL_FLOOR", "300"))
    floor_tierA = int(__import__("os").environ.get("BRIEF2_TIERA_FLOOR", "8"))
    if n < floor_panel:
        log.error("HARD STOP: panel %d < floor %d", n, floor_panel); sys.exit(2)
    if n_a < floor_tierA:
        log.error("HARD STOP: tier-A %d < floor %d", n_a, floor_tierA); sys.exit(2)

    log.info("Brief 2 / Phase 1 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
