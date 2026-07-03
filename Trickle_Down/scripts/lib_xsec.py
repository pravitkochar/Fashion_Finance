"""Small cross-sectional backtester. Import as:  import lib_xsec as lx

Deliberately plain: fixed weights between rebalances (no intra-period drift),
costs charged on turnover at each rebalance, metrics computed exactly as
pre-registered in DECISIONS.md — sharpe, ir, hit_rate, car, max_drawdown.
Nothing here optimizes anything; it prices a weight schedule.

Public API:
    fetch_prices(tickers, start, end, out_path)   yfinance -> prices CSV
    load_prices(path)                             CSV -> wide daily returns
    period_returns(returns_wide, start, end)      compounded return per ticker
    excess_returns(returns_wide, bench_map, bench_wide)
    apply_turnover_cap(w_prev, w_target, cap)     one-way turnover cap
    portfolio_path(weights_by_date, returns_wide, cost_bps)
    metrics(port_daily, bench_daily, periods_per_year, period_rets=None)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

import lib_trickle as lt

log = logging.getLogger("lib_xsec")

TRADING_DAYS = 252


# ------------------------------------------------------------- prices -------

def fetch_prices(tickers: list[str], start: str, end: str,
                 out_path: Path) -> pd.DataFrame:
    """Download adjusted closes ticker-by-ticker (retry once), upsert to CSV.

    Never raises on a bad ticker — logs and moves on, so one dead symbol
    (e.g. TOD.MI post-delisting) cannot sink a refresh.
    """
    import yfinance as yf

    frames = []
    for ticker in tickers:
        got = None
        for attempt in (1, 2):
            try:
                px = yf.download(ticker, start=start, end=end,
                                 progress=False, auto_adjust=True)
                if px is not None and not px.empty:
                    got = px
                    break
                log.warning("fetch %s attempt %d: empty frame", ticker, attempt)
            except Exception as exc:  # network/parse — log, retry once
                log.warning("fetch %s attempt %d failed: %s", ticker, attempt, exc)
            time.sleep(2)
        if got is None:
            log.error("fetch FAILED for %s — skipped", ticker)
            continue
        close = got["Close"]
        if isinstance(close, pd.DataFrame):          # yfinance multi-col quirk
            close = close.iloc[:, 0]
        close = close.dropna()
        frame = pd.DataFrame({
            "date": close.index.strftime("%Y-%m-%d"),
            "ticker": ticker,
            "adj_close": close.values,
        })
        frame["daily_return"] = close.pct_change().values
        frames.append(frame)
        time.sleep(0.5)
    if not frames:
        log.error("fetch_prices: nothing downloaded")
        return pd.DataFrame(columns=["date", "ticker", "adj_close", "daily_return"])
    new = pd.concat(frames, ignore_index=True)
    n = lt.upsert_csv(new, out_path, keys=["date", "ticker"],
                      sort_by=["ticker", "date"])
    log.info("prices upserted: %d tickers ok of %d, %d total rows -> %s",
             len(frames), len(tickers), n, out_path)
    return new


def load_prices(path: Path) -> pd.DataFrame:
    """prices CSV -> wide daily-return DataFrame (date index, ticker cols)."""
    df = pd.read_csv(path, parse_dates=["date"])
    wide = df.pivot_table(index="date", columns="ticker",
                          values="daily_return", aggfunc="last")
    return wide.sort_index()


def period_returns(returns_wide: pd.DataFrame, start, end) -> pd.Series:
    """Compounded return per ticker over (start, end]."""
    window = returns_wide.loc[(returns_wide.index > pd.Timestamp(start))
                              & (returns_wide.index <= pd.Timestamp(end))]
    return (1 + window.fillna(0)).prod() - 1


def excess_returns(returns_wide: pd.DataFrame, bench_map: dict,
                   bench_wide: pd.DataFrame) -> pd.DataFrame:
    """Local-index excess returns; unmapped tickers go basket-neutral.

    bench_map: ticker -> index symbol or None. None (or index missing from
    bench_wide) subtracts the equal-weight mean of the traded universe —
    the pre-registered fallback for e.g. IVL.BK.
    """
    ew = returns_wide.mean(axis=1)
    out = {}
    for ticker in returns_wide.columns:
        bench = bench_map.get(ticker)
        if bench and bench in bench_wide.columns:
            out[ticker] = returns_wide[ticker] - bench_wide[bench]
        else:
            if bench:
                log.warning("bench %s for %s not in price panel — "
                            "using basket-neutral", bench, ticker)
            out[ticker] = returns_wide[ticker] - ew
    return pd.DataFrame(out)


# ---------------------------------------------------------- portfolio -------

def apply_turnover_cap(w_prev: pd.Series, w_target: pd.Series,
                       cap: float = 0.5) -> pd.Series:
    """Scale the trade toward target so one-way turnover <= cap.

    One-way turnover = sum(|delta w|) / 2. If the desired trade exceeds the
    cap, the whole trade vector is scaled down proportionally (keeps the
    cross-sectional bet shape, shrinks its size).
    """
    idx = w_prev.index.union(w_target.index)
    prev = w_prev.reindex(idx).fillna(0.0)
    target = w_target.reindex(idx).fillna(0.0)
    trade = target - prev
    oneway = trade.abs().sum() / 2.0
    if oneway <= cap or oneway == 0:
        return target
    return prev + trade * (cap / oneway)


def portfolio_path(weights_by_date: dict, returns_wide: pd.DataFrame,
                   cost_bps: float = 20.0) -> tuple[pd.Series, pd.Series]:
    """Price a weight schedule. Returns (daily net returns, equity curve).

    weights_by_date: {pd.Timestamp: Series(ticker -> weight)} — already
    turnover-capped by the caller. Weights are held fixed between rebalances.
    Cost = cost_bps/1e4 * sum(|delta w|), charged on the first trading day
    after each rebalance (both sides of every trade pay).
    """
    if not weights_by_date:
        empty = pd.Series(dtype=float)
        return empty, empty
    reb_dates = sorted(weights_by_date)
    daily = []
    prev_w = pd.Series(dtype=float)
    for i, t0 in enumerate(reb_dates):
        t1 = reb_dates[i + 1] if i + 1 < len(reb_dates) else None
        w = weights_by_date[t0]
        mask = returns_wide.index > pd.Timestamp(t0)
        if t1 is not None:
            mask &= returns_wide.index <= pd.Timestamp(t1)
        window = returns_wide.loc[mask]
        if window.empty:
            prev_w = w
            continue
        held = w.reindex(window.columns).fillna(0.0)
        rets = window.fillna(0.0).mul(held, axis=1).sum(axis=1)
        turnover = (w.reindex(w.index.union(prev_w.index)).fillna(0.0)
                    - prev_w.reindex(w.index.union(prev_w.index)).fillna(0.0)
                    ).abs().sum()
        rets.iloc[0] -= (cost_bps / 1e4) * turnover
        daily.append(rets)
        prev_w = w
    if not daily:
        empty = pd.Series(dtype=float)
        return empty, empty
    port = pd.concat(daily).sort_index()
    port = port[~port.index.duplicated(keep="first")]
    equity = (1 + port).cumprod()
    return port, equity


# ------------------------------------------------------------- metrics ------

def _annualized_ratio(series: pd.Series) -> float | None:
    s = series.dropna()
    if len(s) < 20 or s.std(ddof=1) == 0:
        return None
    return float(s.mean() / s.std(ddof=1) * np.sqrt(TRADING_DAYS))


def metrics(port_daily: pd.Series, bench_daily: pd.Series | None,
            periods_per_year: int, period_rets: pd.Series | None = None) -> dict:
    """Exactly the pre-registered metrics (DECISIONS.md) — nothing else.

    hit_rate uses per-rebalance-period returns when supplied, else calendar
    months. periods_per_year is recorded for context; sharpe/ir annualize
    from the daily series with sqrt(252).
    """
    port = port_daily.dropna()
    if port.empty:
        return {"status": "no_data"}
    equity = (1 + port).cumprod()
    out = {
        "sharpe": _annualized_ratio(port),
        "ir": None,
        "hit_rate": None,
        "car": float(equity.iloc[-1] - 1),
        "max_drawdown": float((equity / equity.cummax() - 1).min()),
        "n_days": int(len(port)),
        "periods_per_year": periods_per_year,
    }
    if bench_daily is not None:
        aligned = pd.concat([port, bench_daily], axis=1, join="inner").dropna()
        if len(aligned) >= 20:
            out["ir"] = _annualized_ratio(aligned.iloc[:, 0] - aligned.iloc[:, 1])
    if period_rets is None:
        period_rets = (1 + port).resample("ME").prod() - 1
    period_rets = period_rets.dropna()
    if len(period_rets):
        out["hit_rate"] = float((period_rets > 0).mean())
        out["n_periods"] = int(len(period_rets))
    return {k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in out.items()}
