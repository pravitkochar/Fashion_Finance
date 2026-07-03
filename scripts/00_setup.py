"""Phase 0 — environment + folder setup, yfinance smoke test.

Hard stop: yfinance returns empty for MC.PA Jan 2024 -> exit 1.
Idempotent: safe to re-run.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("phase0")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
SCRIPTS = ROOT / "scripts"


def ensure_folders() -> None:
    for p in (DATA, REPORTS, SCRIPTS):
        p.mkdir(parents=True, exist_ok=True)
    log.info("folders ok: data/ reports/ scripts/")


def smoke_test_yfinance() -> None:
    import yfinance as yf

    log.info("smoke-testing yfinance with MC.PA 2024-01-01..2024-02-01")
    df = yf.download(
        "MC.PA",
        start="2024-01-01",
        end="2024-02-01",
        progress=False,
        auto_adjust=True,
    )
    if df is None or df.empty:
        log.error("yfinance returned empty for MC.PA — HARD STOP")
        sys.exit(1)
    log.info("yfinance ok: MC.PA returned %d rows", len(df))


def main() -> int:
    ensure_folders()
    smoke_test_yfinance()
    log.info("Phase 0 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
