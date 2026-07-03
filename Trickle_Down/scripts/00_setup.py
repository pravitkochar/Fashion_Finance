"""P0 — validate the scaffold: dirs, configs, env keys, parent-repo links.

Run first, and again any time configs change. Exits non-zero on a hard
problem; env-key warnings are soft (only the scripts that need them fail).
"""
from __future__ import annotations

import os
import sys
from collections import Counter

import lib_trickle as lt

log = lt.get_logger("00_setup")


def check_universe() -> list[str]:
    problems = []
    uni = lt.load_universe()
    for tier in ("tier1_runway", "tier2_retailers", "tier3_suppliers", "commodities"):
        if not uni.get(tier):
            problems.append(f"universe.json missing/empty: {tier}")
    slugs = [h["slug"] for h in uni["tier1_runway"]]
    dupes = [s for s, n in Counter(slugs).items() if n > 1]
    if dupes:
        problems.append(f"duplicate tier1 slugs: {dupes}")
    keys = [r["key"] for r in uni["tier2_retailers"]]
    dupes = [k for k, n in Counter(keys).items() if n > 1]
    if dupes:
        problems.append(f"duplicate tier2 keys: {dupes}")
    anchors = [h for h in uni["tier1_runway"] if h["role"] == "anchor"]
    log.info("universe: %d tier1 houses (%d anchors), %d retailers, %d suppliers",
             len(slugs), len(anchors), len(keys), len(uni["tier3_suppliers"]))
    return problems


def check_taxonomy() -> list[str]:
    problems = []
    tax = lt.load_taxonomy()
    alias_owner: dict[str, str] = {}
    for canon, spec in tax["materials"].items():
        for a in [canon] + spec["aliases"]:
            a = a.lower()
            if a in alias_owner and alias_owner[a] != canon:
                problems.append(f"alias '{a}' claimed by both "
                                f"{alias_owner[a]} and {canon}")
            alias_owner[a] = canon
    # parser sanity — locked examples; if these break, the contract broke
    cases = {
        "87% cotton, 13% elastane": {"cotton": 0.87, "elastane": 0.13},
        "OUTER SHELL 100% polyester": {"polyester": 1.0},
        "Shell: 100% Polyamide; Lining: 100% Cotton": {"nylon": 0.5, "cotton": 0.5},
        "52% Viscose 48% Lyocell": {"viscose": 1.0},
        "100% acrylic": {"other": 1.0},
    }
    for text, want in cases.items():
        got = lt.parse_composition(text)
        for mat, share in want.items():
            if abs(got.get(mat, 0) - share) > 0.01:
                problems.append(f"parse_composition({text!r}) -> {got}, "
                                f"expected {want}")
                break
    log.info("taxonomy: %d materials, %d aliases, parser cases %s",
             len(tax["materials"]), len(alias_owner),
             "OK" if not any("parse_composition" in p for p in problems) else "FAIL")
    return problems


def check_seasons() -> list[str]:
    problems = []
    seasons = lt.iter_seasons(2015)
    if seasons[0] != "FW2015":
        problems.append(f"season iteration starts at {seasons[0]}, want FW2015")
    if sorted(seasons, key=lt.season_sort_key) != seasons:
        problems.append("iter_seasons not in chronological show order")
    log.info("seasons: %d fully-known seasons, %s .. %s",
             len(seasons), seasons[0], seasons[-1])
    return problems


def check_environment() -> None:
    for var, needed_by in [("GEMINI_API_KEY", "02_tag_gemini"),
                           ("FMP_API_KEY", "fundamentals overlay (optional)")]:
        state = "set" if os.environ.get(var) else "MISSING"
        log.info("env %s: %s (needed by %s)", var, state, needed_by)
    if lt.PARENT_PRICES.exists():
        log.info("parent panel found: %s", lt.PARENT_PRICES)
    else:
        log.warning("parent prices_raw.csv not found at %s — H3/parent tie-in "
                    "unavailable, Tier2/3 prices unaffected", lt.PARENT_PRICES)


def main() -> int:
    lt.ensure_dirs()
    problems = check_universe() + check_taxonomy() + check_seasons()
    check_environment()
    if problems:
        for p in problems:
            log.error("SETUP PROBLEM: %s", p)
        return 1
    log.info("P0 setup OK — scaffold valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
