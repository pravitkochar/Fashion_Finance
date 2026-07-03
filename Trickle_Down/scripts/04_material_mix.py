"""P1/P2 — aggregate raw look/item tags into the two mix tables.

Inputs:  data/runway/runway_looks.csv + runway_tags.csv
         data/downstream/downstream_items.csv + downstream_tags.csv
Outputs: data/runway_mix.csv     (contract in lib_trickle; season rows carry
                                  delta_vs_trail3 / is_emergent extras)
         data/downstream_mix.csv (contract + thin_sample extra)

Aggregation rules (locked, see DECISIONS.md):
  - a look/item with no share for material M contributes 0 for M — means are
    over full vectors, not just rows where the material appears
  - season-level mix is EQUAL-WEIGHT across brands with >= MIN_LOOKS tagged
    looks that season (avoids big-show bias)
  - downstream months with < THIN_N tagged items are kept but flagged
    thin_sample=True and excluded downstream (06/07)
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

import lib_trickle as lt

log = lt.get_logger("04_material_mix")

MIN_LOOKS = 5     # brand-season eligibility floor for the season vector
THIN_N = 30       # downstream retailer-month sample floor


def _require(path, what: str) -> pd.DataFrame:
    df = lt.read_csv_or_empty(path)
    if df.empty:
        log.error("missing/empty upstream input: %s (%s) — run the "
                  "upstream script first", path, what)
        sys.exit(1)
    return df


def _to_long(wide: pd.DataFrame, value_name: str = "share") -> pd.DataFrame:
    return (wide.reset_index()
            .melt(id_vars=[c for c in wide.index.names], var_name="material",
                  value_name=value_name))


def build_runway_mix() -> None:
    looks = _require(lt.RUNWAY / "runway_looks.csv", "01_scrape_runway")
    tags = _require(lt.RUNWAY / "runway_tags.csv", "02_tag_gemini")
    mats = lt.canonical_materials()

    joined = tags.merge(looks[["look_id", "brand_slug", "season_code"]],
                        on="look_id", how="inner")
    if joined.empty:
        log.error("runway tags and looks do not join on look_id")
        sys.exit(1)

    wide = (joined.pivot_table(index=["brand_slug", "season_code", "look_id"],
                               columns="material", values="share",
                               aggfunc="sum", fill_value=0.0)
            .reindex(columns=mats, fill_value=0.0))

    grp = ["brand_slug", "season_code"]
    brand_mix = wide.groupby(level=grp).mean()
    n_looks = wide.groupby(level=grp).size().rename("n_looks")

    # ---- brand-level rows -------------------------------------------------
    brand_long = _to_long(brand_mix)
    brand_long = brand_long.merge(n_looks.reset_index(), on=grp)
    brand_long["level"] = "brand"
    brand_long["key"] = brand_long["brand_slug"]
    brand_long["known_date"] = brand_long["season_code"].map(
        lambda c: lt.season_known_date(c).isoformat())
    brand_long["delta_vs_trail3"] = np.nan
    brand_long["is_emergent"] = False

    # ---- season-level rows (equal-weight across eligible brands) ----------
    eligible = n_looks[n_looks >= MIN_LOOKS]
    excluded = n_looks[n_looks < MIN_LOOKS]
    for (slug, code), n in excluded.items():
        log.info("season vector: excluding %s %s (only %d tagged looks, "
                 "floor %d)", slug, code, n, MIN_LOOKS)
    if eligible.empty:
        log.error("no brand-season has >= %d tagged looks — cannot build "
                  "season vectors", MIN_LOOKS)
        sys.exit(1)

    season_mix = brand_mix.loc[eligible.index].groupby(level="season_code").mean()
    season_n = eligible.groupby(level="season_code").sum().rename("n_looks")

    order = sorted(season_mix.index, key=lt.season_sort_key)
    season_mix = season_mix.loc[order]
    trail3 = season_mix.rolling(3, min_periods=3).mean().shift(1)
    delta = season_mix - trail3

    season_long = _to_long(season_mix)
    delta_long = _to_long(delta, value_name="delta_vs_trail3")
    season_long = season_long.merge(delta_long, on=["season_code", "material"])
    season_long = season_long.merge(season_n.reset_index(), on="season_code")
    season_long["level"] = "season"
    season_long["key"] = "ALL"
    season_long["known_date"] = season_long["season_code"].map(
        lambda c: lt.season_known_date(c).isoformat())
    season_long["is_emergent"] = season_long["delta_vs_trail3"] > 0.02

    cols = ["level", "key", "season_code", "material", "share", "n_looks",
            "known_date", "delta_vs_trail3", "is_emergent"]
    out = pd.concat([brand_long[cols], season_long[cols]], ignore_index=True)
    out["share"] = out["share"].round(6)
    out["delta_vs_trail3"] = out["delta_vs_trail3"].astype(float).round(6)

    n = lt.upsert_csv(out, lt.DATA / "runway_mix.csv",
                      keys=["level", "key", "season_code", "material"],
                      sort_by=["level", "key", "season_code", "material"])
    log.info("runway_mix.csv: %d rows total (%d brand-seasons, %d seasons, "
             "%d emergent flags this build)", n, len(brand_mix),
             len(season_mix), int(season_long["is_emergent"].sum()))


def build_downstream_mix() -> None:
    items = _require(lt.DOWNSTREAM / "downstream_items.csv",
                     "03_scrape_downstream")
    tags = _require(lt.DOWNSTREAM / "downstream_tags.csv",
                    "03_scrape_downstream")
    mats = lt.canonical_materials()

    joined = tags.merge(items[["item_id", "retailer", "first_seen"]],
                        on="item_id", how="inner")
    if joined.empty:
        log.error("downstream tags and items do not join on item_id")
        sys.exit(1)
    joined["month"] = (pd.to_datetime(joined["first_seen"])
                       .dt.to_period("M").astype(str))

    wide = (joined.pivot_table(index=["retailer", "month", "item_id"],
                               columns="material", values="share",
                               aggfunc="sum", fill_value=0.0)
            .reindex(columns=mats, fill_value=0.0))

    grp = ["retailer", "month"]
    mix = wide.groupby(level=grp).mean()
    n_items = wide.groupby(level=grp).size().rename("n_items")

    out = _to_long(mix)
    out = out.merge(n_items.reset_index(), on=grp)
    out["known_date"] = out["month"].map(
        lambda m: pd.Period(m, freq="M").end_time.date().isoformat())
    out["thin_sample"] = out["n_items"] < THIN_N
    out["share"] = out["share"].round(6)

    thin = n_items[n_items < THIN_N]
    for (retailer, month), n in thin.items():
        log.info("thin sample: %s %s has %d tagged items (floor %d) — kept "
                 "but flagged", retailer, month, n, THIN_N)

    cols = ["retailer", "month", "material", "share", "n_items",
            "known_date", "thin_sample"]
    n = lt.upsert_csv(out[cols], lt.DATA / "downstream_mix.csv",
                      keys=["retailer", "month", "material"],
                      sort_by=["retailer", "month", "material"])
    log.info("downstream_mix.csv: %d rows total (%d retailer-months, "
             "%d thin)", n, len(mix), len(thin))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--which", choices=["runway", "downstream", "both"],
                    default="both")
    args = ap.parse_args()
    lt.ensure_dirs()
    if args.which in ("runway", "both"):
        build_runway_mix()
    if args.which in ("downstream", "both"):
        build_downstream_mix()
    return 0


if __name__ == "__main__":
    sys.exit(main())
