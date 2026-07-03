# Trickle_Down — Runway→High-Street→Materials Trend Cascade

## Goal
Quantify how fashion trends propagate down the cascade (runway → mass retail →
material demand), turn the propagation into point-in-time company signals, and
backtest them honestly. This is the flagship project of the Fashion Thing repo;
it is self-contained here and designed to grow.

## Objectivity charter (read first, non-negotiable)
We are looking for signal, but OBJECTIVE signal. Rules:
1. **Pre-registration.** Hypotheses, universes, metrics, and rebalance cadence
   are locked below and in DECISIONS.md BEFORE the first backtest run. Any
   change afterward must be appended to DECISIONS.md with rationale BEFORE the
   rerun — no silent tweaking until the numbers look good.
2. **Point-in-time discipline.** Every derived row carries a `known_date`
   (show date / scrape date / publication date). A signal at rebalance date T
   may only use rows with known_date ≤ T. No look-ahead, ever.
3. **Negative results are results.** If the cascade doesn't predict returns,
   we write that up with the same rigor. Do NOT iterate the methodology until
   something "works."
4. **Multiple-testing honesty.** We test 2 primary hypotheses + pre-declared
   robustness variants. Report all runs, not the best one. Flag anything
   discovered post-hoc as exploratory.
5. **Costs and turnover.** Headline results are always net of transaction
   costs (20 bps per side default) with the turnover cap applied.

## Pre-registered hypotheses
- **H1 (adoption-speed factor).** Retailers that converge faster/more
  accurately to the runway material mix outperform slow adopters.
  Cross-sectional long/short on Tier-2 retailers, top vs bottom tercile,
  seasonal rebalance (primary) + monthly (robustness).
- **H2 (material-demand nowcast).** When the downstream mix tilts toward
  fiber X, fiber-X suppliers (Tier 3) outperform; commodity refs (CT=F, CL=F)
  used as sanity checks, not tradeable claims.
- **H3 (exploratory, optional).** Luxury margin tilt from trend richness on
  the parent panel. Explicitly exploratory — not a headline claim.

## The cascade (three tiers)
- **Tier 1 — Runway (leading indicator).** ~23 houses across NY/London/Milan/
  Paris, SS+FW, backfilled to 2015. Anchored on the parent panel houses so it
  ties to ../data/prices_raw.csv. See config/universe.json → tier1_runway.
- **Tier 2 — Mass adoption.** Listed fast-fashion/high-street: Inditex, H&M,
  Fast Retailing, Zalando, ASOS, Next, AB Foods/Primark, Gap, ANF, URBN, AEO.
  Shein private → Google Trends proxy. See universe.json → tier2_retailers.
- **Tier 3 — Materials/suppliers.** Indorama (IVL.BK), Toray (3402.T),
  Reliance (RELIANCE.NS), Lenzing (LNZ.VI) + commodities CT=F (cotton),
  CL=F (oil→synthetics), LE=F (leather, loose). universe.json → tier3.

## Materials taxonomy (the primitive)
12 canonical materials + `other` catch-all, defined with parsing aliases in
config/material_taxonomy.json: cotton, denim, wool, cashmere, silk, leather,
linen, viscose (incl rayon/lyocell/modal), polyester, nylon, elastane,
technical. Colors are secondary (top-N seasonal palette). Unmapped fibers go
to `other` — never silently dropped or reassigned.

## Signal construction
1. **Runway mix** — Gemini vision tags every look (materials %, colors,
   category) → material_mix[brand, season]; aggregate to season vector; flag
   emergent materials (share rising vs trailing 3-season mean).
2. **Downstream mix** — retailer new-arrivals composition fields ("87% cotton,
   13% elastane") → material_mix[retailer, month]. Gold data: measured
   propagation, not guessed.
3. **Propagation & lag** — cross-correlate runway vs downstream mix per
   retailer/material → lag L (months) + adoption coefficient.
4. **Signals** — H1: rank retailers by adoption speed/accuracy, long fast /
   short slow. H2: downstream tilt toward fiber X → supplier nowcast.

## Downstream sourcing (decided 2026-07-02)
Scrape + fallbacks. 03_scrape_downstream.py is adapter-based
(`CatalogSource` interface): live scrapers for Zara/H&M/Uniqlo/ASOS first,
polite rate limits, resume-safe. Fallback adapters: local dataset files
(Kaggle/Apify dumps dropped into data/downstream/datasets/) and Google Trends
proxy. If a retailer blocks us, we log it and swap the adapter — the schema
downstream never changes.

## Backtest design (locked)
- Cadence: **seasonal primary (2×/yr), monthly robustness variant.**
- Construction: cross-sectional L/S terciles on Tier-2 adoption factor;
  separate Tier-3 sleeve from the nowcast. Equal-weight within leg.
- Controls: local-index excess returns (bench map in universe.json),
  20 bps/side costs, 50%/rebalance one-way turnover cap, confounder overlay
  reusing the parent repo's earnings-window pattern.
- Metrics: Sharpe/IR, hit rate, CAR, max drawdown vs XRT benchmark.
- History: signals from FW2016 (needs 1 trailing season), returns to 2025.

## Repo layout
- config/universe.json, config/material_taxonomy.json — locked inputs
- scripts/lib_trickle.py — paths, taxonomy, season math, composition parser,
  PIT helpers, IO. Import as `import lib_trickle as lt`. ALL contracts live in
  its docstring.
- scripts/lib_xsec.py — small cross-sectional backtester (built in P4)
- Pipeline (each runnable standalone, resume-safe, idempotent writes):
  - 00_setup.py — dirs, config validation, env checks
  - 01_scrape_runway.py — Vogue Runway looks + images (reuse parent repo's
    01_scrape_vogue.py slug/alias/resume pattern)
  - 02_tag_gemini.py — Gemini vision → look tags (needs GEMINI_API_KEY)
  - 03_scrape_downstream.py — adapter-based catalog scrape → items+tags
  - 04_material_mix.py — looks/items → runway_mix.csv, downstream_mix.csv
  - 05_google_trends.py — pytrends material/color terms → trends.csv
  - 06_propagation_lag.py — cross-correlation → propagation.csv
  - 07_signals.py — adoption factor + nowcast → signals_*.csv
  - 08_backtest.py — L/S backtest, seasonal + monthly → reports/
  - 09_dashboard.py — self-contained HTML dashboard → dashboard/index.html
- Shared with parent repo (DO NOT re-scrape): ../data/prices_raw.csv (parent
  panel), ../data/confounders.csv pattern, ../scripts/lib_event_study.py.

## Build order
P0 taxonomy+universe lock (DONE — this scaffold) → P1 runway mix (2 seasons
first, then backfill to 2015) → P2 downstream mix (Zara+H&M+Uniqlo first) →
P3 propagation/lag → P4 retailer signal + backtest → P5 supplier sleeve +
commodities → P6 dashboard + public site. Light up in order; see signal early.

## Hard stops / soft logs
- Hard: Vogue Runway blocked (cumulative 403/429 > 10); <8 houses/season
  taggable; ALL downstream adapters (scrape + dataset + trends) dead.
- Soft: single retailer blocked → swap adapter, log to data/_source_log.csv;
  Gemini tag parse failure → data/runway/_tag_failures.csv; missing
  composition field → item kept with tags empty, excluded from mix n_items.

## Environment
- Venv: `~/.venvs/trickle_down` (Python 3.13, built with uv from
  requirements.txt). Run everything as
  `~/.venvs/trickle_down/bin/python scripts/XX_*.py` from this folder.
- Do NOT create a venv inside this repo: ~/Documents is iCloud-synced and
  iCloud evicts files ("dataless"), which makes imports hang indefinitely —
  this killed the parent repo's ../.venv. Data CSVs here are also subject to
  eviction; if a script hangs reading an old file, that's why
  (`brctl download <path>` to rehydrate).
- Secrets: `~/.config/trickle_down/env` (chmod 600, outside iCloud) —
  auto-loaded into os.environ by lib_trickle at import. Holds GEMINI_API_KEY
  plus the full free-tier API stack (Groq/Mistral/OpenRouter vision fallbacks,
  FMP/Finnhub/Tiingo/FRED/EIA/etc).

## Published site (3 pages, rebuilt daily by 09 + 16)
- /live dashboard:
  https://claude.ai/code/artifact/57a50a53-698c-431c-a44f-0d9cfe8a4723
- /historical (dashboard/historical.html):
  https://claude.ai/code/artifact/ddd3c092-3b9f-4ce3-9816-3987d2292233
- /predictions (dashboard/predictions.html):
  https://claude.ai/code/artifact/1a5cf72b-e103-4b2a-b53d-9c8e00f88c96
- 09_dashboard.py emits dashboard/artifact.html (content-only copy) each
  build; to refresh the live page, publish that file to the URL above via the
  Artifact tool (pass the URL so it redeploys instead of minting a new one).

## Automation
- launchd job `com.pravit.trickledown.daily` runs scripts/daily_run.sh at
  18:30 local daily (plist in ~/Library/LaunchAgents): runway delta scrape →
  Gemini tag backfill (--limit 220/day, free-tier paced) → downstream
  snapshot → trends refresh → confounders → full 04→09 rebuild.
- Logs: reports/logs/daily_YYYYMMDD.log (30-day retention) +
  /tmp/trickledown_launchd.log for launchd-level errors.
- Status check: `launchctl list | grep trickledown`; data freshness is on the
  dashboard's health panel.

## Token discipline (matches parent repo)
- Scripts run as subprocesses; logging.INFO only, no print().
- One announcement per phase. File writes idempotent. No commits unless asked.
- Every scraper: resume via progress JSON, --limit flag for smoke tests.

## Definition of done (per phase)
- P1: runway_looks ≥ 60% of house-seasons since 2015; runway_mix.csv covers
  ≥ 18 seasons. P2: downstream_mix.csv ≥ 24 months × ≥ 3 retailers.
- P3: propagation.csv with lag + coef per (retailer, material), n_obs ≥ 12.
- P4: backtest report (seasonal + monthly) with ALL pre-registered metrics,
  net of costs, + findings.json. P6: dashboard/index.html renders offline.
