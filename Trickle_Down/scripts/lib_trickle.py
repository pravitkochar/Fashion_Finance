"""Trickle_Down shared library. Import as:  import lib_trickle as lt

Every pipeline script gets paths, config loaders, the composition parser,
season math, point-in-time helpers, and idempotent IO from here. If a contract
changes, it changes here first and DECISIONS.md gets an entry.

Data contracts (CSV, UTF-8, ISO dates; derived tables carry known_date):
    data/runway/runway_looks.csv
        look_id, brand_slug, parent_ticker, city, season_code, show_date,
        image_url, source_url, scraped_at
    data/runway/runway_tags.csv       look_id, material, share
    data/runway/runway_colors.csv     look_id, color, weight
    data/runway/runway_categories.csv look_id, category
    data/downstream/downstream_items.csv
        item_id, retailer, ticker, product_name, category, url, first_seen,
        composition_raw, price, currency, source
    data/downstream/downstream_tags.csv   item_id, material, share
    data/runway_mix.csv
        level (brand|season), key, season_code, material, share, n_looks,
        known_date; season-level rows also carry delta_vs_trail3, is_emergent
    data/downstream_mix.csv
        retailer, month (YYYY-MM), material, share, n_items, known_date,
        thin_sample (True when n_items < 30)
    data/trends/trends.csv
        date, term, term_type (material|color|proxy), material, value,
        known_date
    data/propagation.csv
        retailer, material, lag_months, adoption_coef, r, n_obs
    data/signals_adoption.csv
        rebalance_date, ticker, score, rank, weight, cadence (seasonal|monthly)
    data/signals_nowcast.csv
        date, material, nowcast_z, direction, tickers
    data/prices/prices_tier23.csv     date, ticker, adj_close, daily_return
    data/_source_log.csv              date, retailer, source, event, detail

Season conventions (locked in DECISIONS.md):
    SS{Y} is shown Sep-Oct of Y-1, known_date Nov 5 of Y-1.
    FW{Y} is shown Feb-Mar of Y,   known_date Apr 5 of Y.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ENV_FILE = Path.home() / ".config" / "trickle_down" / "env"


def load_env(path: Path = ENV_FILE) -> int:
    """Load KEY=VALUE lines into os.environ (existing vars win). Runs at
    import so every script sees the project secrets without shell setup."""
    n = 0
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key and key not in os.environ:
                os.environ[key] = val
                n += 1
    return n


load_env()

# ---------------------------------------------------------------- paths -----

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
RUNWAY = DATA / "runway"
DOWNSTREAM = DATA / "downstream"
TRENDS = DATA / "trends"
PRICES = DATA / "prices"
REPORTS = ROOT / "reports"
DASHBOARD = ROOT / "dashboard"
PARENT_ROOT = ROOT.parent                      # "Fashion Thing" repo root
PARENT_PRICES = PARENT_ROOT / "data" / "prices_raw.csv"

ALL_DIRS = [CONFIG, DATA, RUNWAY, RUNWAY / "images", DOWNSTREAM,
            DOWNSTREAM / "datasets", TRENDS, PRICES, REPORTS,
            REPORTS / "img", DASHBOARD]


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger(name)


# --------------------------------------------------------------- config -----

def load_universe() -> dict:
    with open(CONFIG / "universe.json", encoding="utf-8") as f:
        return json.load(f)


def load_taxonomy() -> dict:
    with open(CONFIG / "material_taxonomy.json", encoding="utf-8") as f:
        return json.load(f)


def canonical_materials(include_other: bool = True) -> list[str]:
    mats = list(load_taxonomy()["materials"].keys())
    return mats if include_other else [m for m in mats if m != "other"]


def signal_materials() -> list[str]:
    """Materials eligible for H1/H2 signals ('other' excluded per taxonomy)."""
    return canonical_materials(include_other=False)


# ---------------------------------------------------- material parsing ------

_ALIAS_MAP: dict[str, str] | None = None
_QUALIFIERS: list[str] | None = None


def _alias_map() -> tuple[dict[str, str], list[str]]:
    global _ALIAS_MAP, _QUALIFIERS
    if _ALIAS_MAP is None:
        tax = load_taxonomy()
        _ALIAS_MAP = {}
        for canon, spec in tax["materials"].items():
            _ALIAS_MAP[canon] = canon
            for a in spec["aliases"]:
                _ALIAS_MAP[a.lower()] = canon
        _QUALIFIERS = [q.lower() for q in tax["qualifier_prefixes"]]
    return _ALIAS_MAP, _QUALIFIERS


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def normalize_material(raw: str) -> str | None:
    """Map a raw fiber name to a canonical material, or None if unmappable."""
    aliases, qualifiers = _alias_map()
    name = _strip_accents(raw.lower().strip())
    name = re.sub(r"[^a-z\- ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return None
    changed = True
    while changed:
        changed = False
        for q in qualifiers:
            if name.startswith(q + " "):
                name = name[len(q) + 1:]
                changed = True
    if name in aliases:
        return aliases[name]
    # longest-alias substring match ("mulberry silk blend" -> silk)
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", name):
            return aliases[alias]
    return None


_PCT_NAME = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%\s*([^\d%,;/|.]+)")
_NAME_PCT = re.compile(r"([^\d%,;/|.]+?)\s*(\d{1,3}(?:[.,]\d+)?)\s*%")


def parse_composition(text: str) -> dict[str, float]:
    """Parse a fabric-composition string into {canonical_material: share}.

    Handles "87% cotton, 13% elastane", "COTTON 100%", multi-part labels
    ("Shell: 100% polyester; Lining: 100% cotton" — parts pooled by share
    mass), and European decimal commas. Shares are normalized to sum to 1.
    Unmappable fiber names accumulate under 'other'. Returns {} if nothing
    parseable.
    """
    if not text or not isinstance(text, str):
        return {}
    pairs = [(pct, name) for pct, name in _PCT_NAME.findall(text)]
    if not pairs:
        pairs = [(pct, name) for name, pct in _NAME_PCT.findall(text)]
    shares: dict[str, float] = {}
    for pct, name in pairs:
        try:
            val = float(pct.replace(",", "."))
        except ValueError:
            continue
        if val <= 0 or val > 100:
            continue
        canon = normalize_material(name) or "other"
        shares[canon] = shares.get(canon, 0.0) + val
    total = sum(shares.values())
    if total <= 0:
        return {}
    return {m: round(v / total, 6) for m, v in shares.items()}


# ------------------------------------------------------------- seasons ------

_SEASON_RE = re.compile(r"^(SS|FW)(\d{4})$")


def parse_season_code(code: str) -> tuple[str, int]:
    m = _SEASON_RE.match(code)
    if not m:
        raise ValueError(f"bad season code: {code!r} (want SS2016 / FW2019)")
    return m.group(1), int(m.group(2))


def season_show_window(code: str) -> tuple[date, date]:
    """Calendar window in which this season's shows happen."""
    s, y = parse_season_code(code)
    if s == "SS":
        return date(y - 1, 8, 25), date(y - 1, 10, 31)
    return date(y, 2, 1), date(y, 3, 31)


def season_known_date(code: str) -> date:
    """Point-in-time date by which the full season's runway mix is knowable."""
    s, y = parse_season_code(code)
    return date(y - 1, 11, 5) if s == "SS" else date(y, 4, 5)


def season_sort_key(code: str) -> tuple[int, int]:
    """Chronological order by SHOW date: FW2016 (Feb 16) < SS2017 (Sep 16)."""
    s, y = parse_season_code(code)
    return (y, 0) if s == "FW" else (y - 1, 1)


def iter_seasons(start_year: int = 2015, until: date | None = None) -> list[str]:
    """Season codes in chronological show order, filtered to fully-known ones.

    start_year is the first SHOW calendar year: FW2015 (shown Feb 2015),
    SS2016 (shown Sep 2015), FW2016, ...
    """
    until = until or date.today()
    out: list[str] = []
    for show_year in range(start_year, until.year + 1):
        for code in (f"FW{show_year}", f"SS{show_year + 1}"):
            if season_known_date(code) <= until:
                out.append(code)
    return out


def month_of(d: date | str) -> str:
    d = pd.Timestamp(d)
    return f"{d.year:04d}-{d.month:02d}"


# ------------------------------------------------------- point-in-time ------

def filter_known_asof(df: pd.DataFrame, asof: date | str,
                      col: str = "known_date") -> pd.DataFrame:
    """The one look-ahead gate. Every signal/backtest read goes through this."""
    if col not in df.columns:
        raise KeyError(f"point-in-time filter needs '{col}' column")
    known = pd.to_datetime(df[col])
    return df.loc[known <= pd.Timestamp(asof)].copy()


# ------------------------------------------------------------------ IO ------

def stable_id(*parts: str, n: int = 12) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def upsert_csv(df_new: pd.DataFrame, path: Path, keys: list[str],
               sort_by: list[str] | None = None) -> int:
    """Idempotent append: merge on keys (new rows win), atomic write.

    Returns the resulting row count.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path)
        df = pd.concat([old, df_new], ignore_index=True)
    else:
        df = df_new.copy()
    df = df.drop_duplicates(subset=keys, keep="last")
    if sort_by:
        df = df.sort_values(sort_by)
    tmp = path.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)
    return len(df)


def read_csv_or_empty(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=columns or [])


def load_progress(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress: dict, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=1, sort_keys=True)
    tmp.replace(path)


def log_source_event(retailer: str, source: str, event: str,
                     detail: str = "") -> None:
    """Append to data/_source_log.csv (adapter swaps, blocks, fallbacks)."""
    row = pd.DataFrame([{"date": date.today().isoformat(), "retailer": retailer,
                         "source": source, "event": event, "detail": detail}])
    path = DATA / "_source_log.csv"
    header = not path.exists()
    row.to_csv(path, mode="a", header=header, index=False)
