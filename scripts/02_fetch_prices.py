"""Phase 2 — fetch daily adjusted close prices for 15 stocks + 6 indices, 2000-2025.

Output: data/prices_raw.csv long format [date, ticker, adj_close, daily_return]
where daily_return = ln(adj_close_t / adj_close_t-1).

Hard stop: >2 tickers fail to return data.
Idempotent: writes whole file each run.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("phase2")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "prices_raw.csv"

COMPANIES = [
    "MC.PA", "KER.PA", "CPRI", "TPR", "COH", "PVH",
    "RMS.PA", "BRBY.L", "1913.HK", "BC.MI", "MONC.MI",
    "BOSS.DE", "RL", "SFER.MI", "TOD.MI",
]
INDICES = ["^FCHI", "^GSPC", "^FTSE", "^HSI", "FTSEMIB.MI", "^GDAXI"]
START = "2000-01-01"
END = "2025-12-31"


def fetch_one(ticker: str) -> pd.DataFrame:
    for attempt in (1, 2):
        try:
            df = yf.download(
                ticker, start=START, end=END,
                progress=False, auto_adjust=True, threads=False,
            )
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                if "Close" not in df.columns:
                    log.warning("%s: no Close column (cols=%s)", ticker, list(df.columns))
                    return pd.DataFrame()
                out = df[["Close"]].rename(columns={"Close": "adj_close"}).copy()
                out["ticker"] = ticker
                out.index.name = "date"
                out = out.reset_index()
                return out
        except Exception as e:
            log.warning("%s attempt %d error: %s", ticker, attempt, e)
            time.sleep(2.0)
    return pd.DataFrame()


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    all_tickers = COMPANIES + INDICES
    frames: list[pd.DataFrame] = []
    failed: list[str] = []

    for tk in tqdm(all_tickers, desc="yfinance"):
        df = fetch_one(tk)
        if df.empty:
            log.error("FAIL %s — empty after retry", tk)
            failed.append(tk)
            continue
        log.info("%s: %d rows %s..%s", tk, len(df), df["date"].min().date(), df["date"].max().date())
        frames.append(df)
        time.sleep(0.4)

    if len(failed) > 2:
        log.error("HARD STOP: %d tickers failed: %s", len(failed), failed)
        sys.exit(2)
    if failed:
        log.warning("excluded with warning: %s", failed)

    big = pd.concat(frames, ignore_index=True)
    big["date"] = pd.to_datetime(big["date"]).dt.tz_localize(None).dt.normalize()
    big = big.sort_values(["ticker", "date"]).reset_index(drop=True)

    big["daily_return"] = (
        big.groupby("ticker", group_keys=False)["adj_close"]
           .apply(lambda s: np.log(s / s.shift(1)))
    )

    big = big[["date", "ticker", "adj_close", "daily_return"]]
    big.to_csv(OUT, index=False)
    log.info("wrote %s rows=%d tickers=%d", OUT, len(big), big["ticker"].nunique())
    log.info("Phase 2 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
