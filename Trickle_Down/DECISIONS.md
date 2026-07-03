# DECISIONS.md — pre-registration & methodology change log

Append-only. Every methodology decision is logged BEFORE the code that uses it
runs against returns data. Changes after the first backtest run require a new
dated entry with rationale — see the Objectivity charter in CLAUDE.md.

---

## 2026-07-02 — Initial pre-registration (P0)

- **Universe locked** as config/universe.json: 23 Tier-1 houses (anchored to
  the 14-parent price panel), 11 listed Tier-2 retailers + Shein proxy,
  4 Tier-3 suppliers + 3 commodity references.
- **Taxonomy locked** as config/material_taxonomy.json: 12 canonical
  materials + `other`; unmapped fibers go to `other`, never reassigned.
- **Hypotheses locked**: H1 adoption-speed L/S on Tier-2 (primary),
  H2 material-demand nowcast on Tier-3 (primary), H3 luxury trend-richness
  tilt (exploratory only).
- **Cadence locked**: seasonal (2×/yr, at season known_date + 1 trading day)
  primary; monthly variant reported as robustness, never promoted post-hoc.
- **Metrics locked**: Sharpe, IR vs XRT, hit rate, CAR, max drawdown; all
  headline numbers net of 20 bps/side, 50% one-way turnover cap.
- **Point-in-time rule**: signal at T uses only rows with known_date ≤ T.
  Season known_date convention: SS(Y) = Nov 5 (Y-1); FW(Y) = Apr 5 (Y).
- **Lag estimation locked**: Pearson cross-correlation of season-aligned
  runway share vs monthly downstream share, lag grid 0–12 months, per
  (retailer, material); require n_obs ≥ 12 else coefficient is NaN and the
  pair is excluded (logged, not imputed).
- **Downstream sourcing decision**: scrape-with-fallback adapters (user call,
  2026-07-02). Adapter swaps are logged in data/_source_log.csv and disclosed
  in any write-up, since source mix affects comparability over time.
- **History split**: 2016–2023 development window; 2024–2025 is a soft
  holdout — we may LOOK at it only after the dev-window methodology is frozen
  via an entry here.

## 2026-07-02 — H1 functional form (pre-registration, before any run)

- Adoption score at rebalance T = correlation, across signal materials,
  between (a) the retailer's downstream mix change over the trailing 12
  months ending at T (last-month share minus first-month share) and (b) the
  movement implied by the most recent runway season vector known BEFORE that
  12-month window began (runway share minus the retailer's window-start
  share). Floors: ≥6 materials in common, ≥6 months of retailer data,
  ≥6 scored retailers per date else the date is skipped and logged.
- Season-level runway vector = equal-weight mean across brands with ≥5
  tagged looks that season (guards against big-show bias).
- Downstream months with n_items < 30 are flagged thin_sample and excluded
  from propagation/signals.

## 2026-07-02 — v1 feasibility addendum (pre-registered BEFORE first run)

Constraint discovered before any signal/backtest run: retailer-level
HISTORICAL material mix is not retroactively obtainable from free sources —
live catalog scraping only yields today's snapshot. Consequences, locked now:

- **H1 (adoption-speed L/S) is FORWARD-ONLY in v1.** The catalog scrapers
  accumulate measured downstream mix from 2026-07 onward; H1 becomes a paper
  track record, evaluated on the pre-registered rules as months accrue. No
  retroactive H1 backtest will be claimed from proxy data.
- **H2 (material-demand nowcast) v1 backtest uses Google Trends as the
  downstream-demand proxy** (per-material trends_terms, monthly, 2015→now,
  known_date = observation date). This is a PROXY and will be labeled as such
  in every output; when ≥24 months of measured catalog mix exist, H2 will be
  re-estimated on measured data and both versions reported.
- **Vision tagging may use multiple free-tier models** (Gemini 2.5 Flash
  primary; Groq Llama-4-Scout / Mistral Pixtral fallback when quota-blocked).
  Model recorded per look in data/runway/_tag_log.csv; per-model mix
  distributions will be compared before pooling, and any systematic
  divergence gets a DECISIONS entry before pooled use.
- **Runway backfill is quota-paced** (free tiers): tagging proceeds
  newest-season-first via a daily automation; backtest depth grows as the
  backfill completes. Coverage stats reported alongside any result.

## 2026-07-03 — V2 pre-registration: historical reconstruction + train/test
(SUPERSEDES the "H1 forward-only" clause above, BEFORE any V2 evaluation)

- New evidence: Wayback Machine CDX probes show dense archived retailer
  product pages (Zara 2017+, H&M 2021+ on current domain, ASOS 2018+; all
  probes hit the 5,000-row cap). Historical retailer mix IS reconstructable
  with snapshot-timestamp known_dates. The forward-only restriction is
  therefore lifted for wherever archive coverage meets the gates below.
- **Splits locked**: TRAIN 2017-01→2022-12; walk-forward folds validating
  2020, 2021, 2022 (expanding fit windows); selection metric = mean fold IR
  vs XRT. TEST 2023-01→2025-12, sealed — evaluated once, only after a
  "MODEL V2 FROZEN" entry here; 08_backtest to enforce via a guard.
- **Tuning grid locked** (nothing outside it): H2 z-gate {0.5,1,1.5},
  trailing {9,12,18}m; H1 terciles/quintiles, adoption window {6,9,12}m;
  lag = fitted ±1m; floors n_items {20,30}, materials {5,6,8}.
- **Coverage gates**: full H1 requires ≥2 retailers × ≥60 months with
  n_items ≥30; otherwise H1 runs on the covered subset with coverage
  disclosed on every output.
- Full plan: PLAN_V2.md. The generative-designs site page is explicitly
  parked (user call, 2026-07-03) pending a proper think-through.

