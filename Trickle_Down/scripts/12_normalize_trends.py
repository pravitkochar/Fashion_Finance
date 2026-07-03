"""P3 (V2) — normalize Google Trends so levels are comparable across years.

Trends values are a relative 0-100 index per term; a '60' in 2016 and a '60'
in 2024 are not the same thing, and term popularity drifts. Two normalized
columns are added per row (raw `value` kept untouched):

    value_yoy   log(value_t / value_{t-12m}), NaN for the first 12 months
    value_z     z-score of `value` vs its trailing 36 months (min 18 obs)

Both are computed strictly from PAST values of the same term — nothing
forward-looking, so known_date semantics are unchanged. P4 fitting uses
value_z (locked in PLAN_V2.md).
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import lib_trickle as lt

log = lt.get_logger("12_normalize_trends")

TRENDS_CSV = lt.TRENDS / "trends.csv"
TRAIL = 36
MIN_OBS = 18


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["term", "date"]).reset_index(drop=True)
    out = []
    for term, g in df.groupby("term", sort=False):
        g = g.copy()
        v = g["value"].astype(float).clip(lower=0.5)     # 0 -> log-safe floor
        g["value_yoy"] = np.log(v / v.shift(12)).round(4)
        mu = v.shift(1).rolling(TRAIL, min_periods=MIN_OBS).mean()
        sd = v.shift(1).rolling(TRAIL, min_periods=MIN_OBS).std(ddof=1)
        g["value_z"] = ((v - mu) / sd.replace(0, np.nan)).round(4)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    df = lt.read_csv_or_empty(TRENDS_CSV)
    if df.empty:
        log.error("trends.csv missing/empty — run 05_google_trends.py first")
        return 1
    df = normalize(df)
    tmp = TRENDS_CSV.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(TRENDS_CSV)
    n_z = int(df["value_z"].notna().sum())
    log.info("trends.csv normalized: %d rows, %d with value_z (%d terms)",
             len(df), n_z, df["term"].nunique())
    # gap check inside the evaluation years
    core = df[(df["date"] >= "2017-01-01") & (df["date"] <= "2025-12-31")]
    gaps = core[core["value_z"].isna()].groupby("term").size()
    for term, n in gaps.items():
        log.warning("term %r: %d NaN z-scores inside 2017-2025", term, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
