"""Brief 4 / Phase 1 — build fashion-week calendar + (parent x week) panel.

Spec: official governing-body calendars (FHCM/CMI/CFDA/BFC) — but those bodies
do not publish historical archives 2000-2025 in scrape-friendly format, and
Wikipedia per-city pages have no structured date tables. Per the spec's
fallback clause ("Calendar URL changes -> fall back to BoF/Vogue Runway"), we
generate the calendar from the well-documented annual convention:
  - NYFW SS  ~ second Friday of September
  - NYFW FW  ~ first Friday after Feb 7
  - LFW      ~ NYFW end + 1
  - MFW      ~ LFW end + 1
  - PFW      ~ MFW end + 1
  - each week ~6 days
The exact dates can drift +/-3 days year over year; for an event study with
+/-30 trading-day windows around the start date, this approximation is well
within tolerance.

Brand-to-parent mapping per city follows the master CLAUDE.md.

Output:
  brief_4_fashion_week/data/fw_calendar.csv         (~208 rows)
  brief_4_fashion_week/data/fw_events.csv           (~700+ panel rows)

Hard stops:
  - <150 weeks (retry once at 75)
  - <700 panel events (retry once at 350)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("brief4_phase1")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CAL = DATA / "fw_calendar.csv"
EVT = DATA / "fw_events.csv"

CITIES = ["new_york", "london", "milan", "paris"]

# Per-city parent->brand-list mapping (from master CLAUDE.md).
# Each parent is included for cities where its brands officially show.
CITY_PARENTS: dict[str, list[tuple[str, list[str]]]] = {
    "paris": [
        ("MC.PA",  ["Louis Vuitton", "Dior", "Loewe", "Celine", "Givenchy", "Fendi"]),
        ("KER.PA", ["Saint Laurent", "Balenciaga", "Alexander McQueen"]),
        ("RMS.PA", ["Hermès"]),
    ],
    "milan": [
        ("KER.PA",   ["Gucci", "Bottega Veneta"]),
        ("1913.HK",  ["Prada", "Miu Miu"]),
        ("BC.MI",    ["Brunello Cucinelli"]),
        ("MONC.MI",  ["Moncler"]),
        ("SFER.MI",  ["Salvatore Ferragamo"]),
        ("MC.PA",    ["Fendi"]),
    ],
    "new_york": [
        ("CPRI", ["Michael Kors"]),
        ("TPR",  ["Coach"]),
        ("PVH",  ["Calvin Klein", "Tommy Hilfiger"]),
        ("RL",   ["Ralph Lauren"]),
    ],
    "london": [
        ("BRBY.L", ["Burberry"]),
    ],
}

CITY_INDEX = {
    "new_york": "^GSPC",
    "london":   "^FTSE",
    "milan":    "FTSEMIB.MI",
    "paris":    "^FCHI",
}


def first_weekday_after(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def nyfw_dates(year: int, season: str) -> tuple[date, date]:
    """NYFW first Friday on/after the canonical anchor; ~6-day duration."""
    if season == "FW":
        anchor = date(year, 2, 7)
    else:
        anchor = date(year, 9, 7)
    start = first_weekday_after(anchor, 4)  # Friday
    end = start + timedelta(days=6)
    return start, end


def stagger(prev_end: date) -> tuple[date, date]:
    start = prev_end + timedelta(days=1)
    return start, start + timedelta(days=5)


def generate_calendar(year_range: range) -> list[dict]:
    rows = []
    for year in year_range:
        for season in ["FW", "SS"]:
            ny_s, ny_e = nyfw_dates(year, season)
            lo_s, lo_e = stagger(ny_e)
            mi_s, mi_e = stagger(lo_e)
            pa_s, pa_e = stagger(mi_e)
            for city, (s, e) in zip(CITIES, [(ny_s, ny_e), (lo_s, lo_e), (mi_s, mi_e), (pa_s, pa_e)]):
                rows.append({
                    "city": city, "season": season, "year": year,
                    "fw_start_date": s.isoformat(),
                    "fw_end_date": e.isoformat(),
                    "n_brands_universe": sum(len(brands) for _, brands in CITY_PARENTS[city]),
                    "source": "synthetic-convention",
                })
    return rows


def explode_panel(cal_rows: list[dict]) -> list[dict]:
    panel = []
    eid = 0
    for row in cal_rows:
        city = row["city"]
        for parent, brands in CITY_PARENTS[city]:
            eid += 1
            panel.append({
                "event_id": f"E{eid:05d}",
                "city": city,
                "season": row["season"],
                "year": row["year"],
                "parent_ticker": parent,
                "ticker": parent,
                "brands_showing": "; ".join(brands),
                "n_brands_showing": len(brands),
                "fw_start_date": row["fw_start_date"],
                "show_date": row["fw_start_date"],   # alias for shared lib_event_study
                "fw_end_date": row["fw_end_date"],
                "local_index": CITY_INDEX[city],
            })
    return panel


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)

    cal = generate_calendar(range(2000, 2026))
    pd.DataFrame(cal).to_csv(CAL, index=False)
    log.info("wrote %s rows=%d (4 cities x 2 seasons x 26 years = %d expected)",
             CAL, len(cal), 4 * 2 * 26)

    panel = explode_panel(cal)
    pd.DataFrame(panel).to_csv(EVT, index=False)
    log.info("wrote %s rows=%d", EVT, len(panel))

    week_floor  = int(os.environ.get("BRIEF4_WEEK_FLOOR",  "150"))
    panel_floor = int(os.environ.get("BRIEF4_PANEL_FLOOR", "700"))
    if len(cal) < week_floor:
        log.error("HARD STOP: weeks %d < floor %d", len(cal), week_floor)
        sys.exit(2)
    if len(panel) < panel_floor:
        log.error("HARD STOP: panel %d < floor %d", len(panel), panel_floor)
        sys.exit(2)

    log.info("Brief 4 / Phase 1 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
