"""Macro confounder series for the controls overlay (FRED + EIA).

Free-key APIs, monthly frequency, 2015→now. These are CONTEXT/CONTROL series
per CLAUDE.md — used to sanity-check that a "signal" isn't just a macro cycle
(oil → polyester costs, retail-sales cycle → all retailers, etc). Not inputs
to H1/H2 scores.

Output: data/confounders_macro.csv  [date, series, value, source, known_date]
known_date = observation month end + 1 month (publication-lag convention,
conservative: FRED monthly series publish with ~2-6 week lag).

Needs env: FRED_API_KEY, EIA_API_KEY (auto-loaded via lib_trickle).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

import pandas as pd
import requests

import lib_trickle as lt

log = lt.get_logger("10_confounders")

FRED_SERIES = {
    "RSCCAS": "retail_sales_clothing",        # retail sales: clothing stores
    "UMCSENT": "consumer_sentiment",          # U Michigan sentiment
    "CPIAPPSL": "cpi_apparel",                # CPI apparel
    "DTWEXBGS": "usd_broad_index",            # trade-weighted USD
}
EIA_SERIES = {
    "PET.RWTC.M": "wti_spot_monthly",         # WTI spot, monthly
}
START = "2015-01-01"


def fetch_fred(api_key: str) -> list[dict]:
    rows = []
    for sid, name in FRED_SERIES.items():
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": sid, "api_key": api_key,
                        "file_type": "json", "observation_start": START},
                timeout=30)
            r.raise_for_status()
            for obs in r.json()["observations"]:
                if obs["value"] in (".", ""):
                    continue
                d = pd.Timestamp(obs["date"])
                rows.append({"date": obs["date"], "series": name,
                             "value": float(obs["value"]), "source": "FRED",
                             "known_date": (d + pd.offsets.MonthEnd(0)
                                            + pd.offsets.MonthEnd(1)).date().isoformat()})
            log.info("FRED %s (%s): ok", sid, name)
        except Exception as e:
            log.error("FRED %s failed: %s", sid, str(e)[:200])
    return rows


def fetch_eia(api_key: str) -> list[dict]:
    rows = []
    for sid, name in EIA_SERIES.items():
        try:
            r = requests.get(
                f"https://api.eia.gov/v2/seriesid/{sid}",
                params={"api_key": api_key}, timeout=30)
            r.raise_for_status()
            for obs in r.json()["response"]["data"]:
                period = str(obs["period"])          # e.g. "2015-01"
                if period < START[:7]:
                    continue
                d = pd.Timestamp(period + "-01")
                rows.append({"date": d.date().isoformat(), "series": name,
                             "value": float(obs["value"]), "source": "EIA",
                             "known_date": (d + pd.offsets.MonthEnd(0)
                                            + pd.offsets.MonthEnd(1)).date().isoformat()})
            log.info("EIA %s (%s): ok", sid, name)
        except Exception as e:
            log.error("EIA %s failed: %s", sid, str(e)[:200])
    return rows


def main() -> int:
    import os
    argparse.ArgumentParser(description=__doc__).parse_args()
    fred_key, eia_key = os.environ.get("FRED_API_KEY"), os.environ.get("EIA_API_KEY")
    if not fred_key or not eia_key:
        log.error("FRED_API_KEY / EIA_API_KEY missing from env")
        return 1
    rows = fetch_fred(fred_key) + fetch_eia(eia_key)
    if not rows:
        log.error("no confounder data fetched")
        return 1
    df = pd.DataFrame(rows)
    n = lt.upsert_csv(df, lt.DATA / "confounders_macro.csv",
                      keys=["date", "series"], sort_by=["series", "date"])
    log.info("confounders_macro.csv: %d rows across %d series",
             n, df["series"].nunique())
    return 0


if __name__ == "__main__":
    sys.exit(main())
