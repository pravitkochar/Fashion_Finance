# Trickle_Down V2 — Historical Cascade Reconstruction, Train/Test Evaluation

## The thesis, restated properly
Runway shows (Tier 1) lead high-street material mixes (Tier 2), which lead
material demand priced into suppliers and commodities (Tier 3). V2 treats
this as a supervised learning problem over HISTORY:

- **Training set**: past seasons where we can observe the full cascade —
  fit propagation lags/coefficients and tune every signal parameter with
  walk-forward folds.
- **Test set**: a sealed, untouched window evaluated exactly once with the
  frozen model — the honest answer to "does this actually make money."
- **Live layer**: the frozen model then nowcasts forward (daily job).

## What changed vs V1 (and why this supersedes the forward-only addendum)
V1 concluded retailer-mix history was unobtainable and made H1 forward-only.
Wrong conclusion: the Internet Archive's Wayback Machine holds dense
snapshots of retailer PRODUCT PAGES — composition fields included — each
stamped with its crawl timestamp (perfectly point-in-time). CDX probe
(2026-07-03, logged): Zara dense from 2017; H&M dense from 2021 on
www2.hm.com (pre-2021 legacy domains to be probed); ASOS from ~2018; all
probes hit the 5,000-row query cap. Historical downstream reconstruction is
feasible. DECISIONS.md gets a superseding entry BEFORE any new evaluation.

## Data splits — LOCKED NOW, before anything is fit
- **TRAIN**: 2017-01 → 2022-12. All fitting and all tuning happens here.
- **Folds** (walk-forward, expanding — time series must not be shuffled):
  - fold 1: fit ≤2019-12, validate 2020 (COVID year — keep, it's real life)
  - fold 2: fit ≤2020-12, validate 2021
  - fold 3: fit ≤2021-12, validate 2022
  - Selection metric: mean fold IR vs XRT (declared here, not after).
- **TEST**: 2023-01 → 2025-12. Sealed. Evaluated once, only after a
  "MODEL V2 FROZEN" entry lands in DECISIONS.md. 08_backtest gets a hard
  guard that refuses the test window without that marker.
- **LIVE**: 2026+ — frozen model, paper track record, daily job.

## Phases

### P0 — Governance (today)
This document + superseding DECISIONS.md entry: splits, fold scheme,
selection metric, tuning grid (below) all pre-registered. No fitting code
runs against returns before this is committed.

### P1 — Wayback downstream reconstruction (the crux)
New script `11_wayback_downstream.py`:
- Per (retailer, month): CDX query (matchType=prefix, collapse=urlkey,
  digest-deduped) over product-page URL patterns; sample ≤120 distinct
  product pages/month; fetch archived HTML via
  `web.archive.org/web/{timestamp}id_/{url}`.
- Parse composition with the SAME per-retailer extractors as the live
  adapters + lt.parse_composition; denim rule applies. Emit
  downstream_items/tags rows with source="wayback", first_seen = snapshot
  date (this IS the known_date — PIT-clean by construction).
- Domain map incl. legacy: zara.com/us/en (2017+ confirmed),
  www2.hm.com/en_us (2021+ confirmed) + probe hm.com/us pre-2021,
  asos.com/us/*/prd/*, uniqlo legacy domains.
- Politeness: ~1 req/2s, resume per (retailer, month), progress JSON;
  the full sweep (~4 retailers × 108 months × ≤120 pages) runs over days
  as a daily-job step; --month/--retailer flags for targeted runs.
- **Pre-registered acceptance gates**: ≥2 retailers with ≥60 months of
  n_items ≥ 30/month → full H1; below that, H1 runs on the covered subset
  and every output discloses coverage. data/wayback_coverage.csv + a
  coverage panel on the site.

### P2 — Runway tag backfill completion
26,855 looks; multi-provider tagging (~1.4–1.6k/day on free tiers) →
~2.5–3 weeks via the daily job. Optional accelerator: paid Gemini key
(~$15 total) finishes it in ~2 days. Per-model mix-distribution divergence
check before pooling (already registered).

### P3 — Trends normalization
trends.csv is a relative index → per-term YoY z-score transform so levels
are comparable across time (new columns, raw kept).

### P4 — Propagation fitting (TRAIN only) — `13_fit_propagation.py`
- runway→retail: lag/coef per (retailer, material), lag grid 0–12 months
- runway→trends: per material (validates the cascade's first hop)
- retail→suppliers/commodities: lag/coef per material vs supplier excess
  returns and commodity refs
- Every read passes lt.filter_known_asof at the fold boundary. Outputs
  per-fold artifacts (propagation_fold{k}.csv) + train-window aggregate.

### P5 — Signal construction + CV tuning — `14_tune_signals.py`
Pre-registered grid (nothing outside it may be tuned):
- H2 z-gate ∈ {0.5, 1.0, 1.5}; trailing window ∈ {9, 12, 18} months
- H1 leg size: terciles vs quintiles; adoption window ∈ {6, 9, 12} months
- lag: fitted best-lag ±1 month
- coverage floors: n_items/month ∈ {20, 30}; materials floor ∈ {5, 6, 8}
Chosen params → config/model_v2.json + "MODEL V2 FROZEN" DECISIONS entry
with the full fold table (every combination's fold IRs — not just the
winner).

### P6 — Sealed test evaluation
08_backtest --window test (guard checks the frozen marker): H1 retailer
L/S, H2 supplier sleeve, commodities as reference only, all pre-registered
metrics net of costs. One run. The result — positive or negative — goes in
DECISIONS.md and on the site. No re-tuning afterward without a new
versioned model (model_v3) and a fresh unseen window.

### P7 — Live nowcast (already running)
Daily job keeps scraping/tagging; frozen model scores new months; paper
track accumulates alongside the test result for regime comparison.

### P8 — Site v2 (multi-page; after P6)
- **/historical** — the aggregate story across all years: season heatmaps,
  measured runway→retail propagation (lags per retailer/material),
  retail→commodity linkage, per-material case studies, fold-by-fold
  results. "What we've seen, measured."
- **/predictions** — the frozen model's forward view: next-season material
  trajectory, expected retailer tilt, supplier/commodity positioning, with
  confidence + coverage caveats. "What we expect."
- **/live** — the current operational dashboard (nowcast gauges, positions,
  data health).
- Same static-prerender architecture (09 v2), artifact-published.
- **PARKED by explicit user call**: a generative "potential designs from
  runway trends" page — do NOT build; think through properly after
  everything above is done (model choice, image rights, what it's for).

## Leakage & honesty guards (system-level)
- known_date on every row: wayback snapshot ts, season known_date, trends
  month-close, transcript publication ts.
- Fold/fit code structurally reads through PITStore/filter_known_asof.
- Test-window guard in 08; full tuning grid disclosed; a negative test
  result ships to the site with the same prominence as a positive one.
- Optional secondary proxy (robustness, disclosed as such): FMP earnings-
  transcript material-mention index per retailer-quarter
  (`15_transcript_mentions.py`).

## Timeline (free-tier pacing)
- Today: P0 done; P1 script + first reconstructed months (Zara 2019 pilot).
- Weeks 1–3: P1 sweep + P2 backfill run themselves via the daily job.
- Data-complete → P3–P5 ≈ 1–2 days, P6 one run, P8 ≈ 1–2 days.
