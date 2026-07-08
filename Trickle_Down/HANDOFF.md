# Trickle_Down — START HERE (master handoff)

**If you are a future Claude session: read this file first, then CLAUDE.md,
then DECISIONS.md. Together they tell you everything about what this project
is, what was built, what was found, and what to do next. All paths are under
`~/Developer/fashion-thing/Trickle_Down/`.**

Owner: Pravit. Repo: github.com/pravitkochar/Fashion_Finance (private-ish;
the whole project is committed and pushed). Venv: `~/.venvs/trickle_down`
(uv, Python 3.13) — NEVER make a venv inside the repo (iCloud/eviction
history; this project lives in ~/Developer specifically to avoid that).
Secrets: `~/.config/trickle_down/env` (chmod 600), auto-loaded by lib_trickle.

---

## What this project is (one paragraph)

An objective test of fashion "trickle-down": do runway fabric trends
propagate to fast-fashion racks and consumer demand, at a measurable lag, and
is any of it tradeable? Built from 26,838 vision-tagged runway looks
(2015–2026, 22 houses), a decade of fast-fashion fabric-mix history
reconstructed from the Internet Archive (Zara/H&M/ASOS/Uniqlo product pages,
each snapshot timestamped = point-in-time), Google Trends, and equity/
commodity prices. Everything is pre-registered (DECISIONS.md) before it runs,
point-in-time throughout, and negative results are published at the same size
as positive ones.

## What we FOUND (the bottom line)

- **PROVEN:** the cascade is real and measured — runway fabric leads consumer
  search by ~3–5 months and H&M/ASOS rack composition by 4–12 months (wool
  the cleanest thread). 43 fitted cross-tier links. This is genuinely novel:
  no prior published work fits multi-quarter cross-tier propagation lags.
- **THE COMMERCIAL CROWN JEWEL:** the same signal calls U.S. clothing-store
  retail-sales TURNING POINTS 10–11 months ahead (precision 0.46 / recall
  0.42 vs an AR(3) baseline at 0.14 / 0.08), built entirely from public data.
- **THE HONEST SPINE:** naive trading does NOT work, proven three ways —
  H1 adoption factor (untestable, archive supports only ~2 retailers deep),
  H2 supplier-stock nowcast (all 9 CV combos negative, best IR −0.39),
  H4 earnings-window event study (null, placebo-refuted). Extended to all
  five attribute channels (materials/color/accessories/silhouette/prints) —
  every tradeable cell dies once selection bias is corrected. Signature:
  *information real, naive trade absent.*
- H5 (a commodity/futures study) was explored then CUT by the user; it is not
  in the paper, deck, or site. Do not resurface it.

## The deliverables (all built, committed, live)

- **Paper**: `paper/trickle_down_paper.md` + `paper/Trickle_Down_Paper.pdf`
  (written in Pravit's voice, no AI-tells; download button on the site).
- **Pitch deck**: `paper/Trickle_Down_Deck.pdf` (13 slides, data-asset framing,
  raw-denim design, honesty spine) + `paper/deck_blueprint.md` (the research
  behind it).
- **Site**: single-page tabbed site `dashboard/index_site.html` (built by
  `scripts/23_site.py`) — Overview / The Cascade / This Season / The Honest
  Part / Live Data, both PDF download buttons in the header. Published at
  https://claude.ai/code/artifact/5c0036f7-5a22-4b77-8a3d-257a23ca6a4e
  (older separate pages story/historical/predictions/index still build but the
  tabbed site is primary).
- **Automation**: launchd `com.pravit.trickledown.daily` @ 18:30 runs
  `scripts/daily_run.sh` (entry point `~/.local/bin/trickledown_daily.sh`,
  outside iCloud) — rescrapes, re-fits, rebuilds every page nightly.

## Where to look for X

- Scope, conventions, universe, environment → **CLAUDE.md**
- Every pre-registered decision + every honest verdict → **DECISIONS.md**
- The V2 pivot (Wayback reconstruction, train/test design) → **PLAN_V2.md**
- Channel matrix, data gaps, next studies, commercialization → **FUTURE_WORK.md**
- Pipeline scripts → `scripts/00_setup.py` … `25_prelim_matrix.py`
  (01 scrape runway, 02 tag, 03/11 downstream, 04 mix, 05/12 trends, 06/13
  propagation, 07 signals, 08 backtest, 09 dashboard, 14 CV tune, 16/18/23
  site, 19 event study, 20 nowcast, 24/25 exploratory screens)
- Results → `reports/` (findings_*.json, cv_results.csv, prelim_matrix.json,
  explore_channels.json, img/)
- Data → `data/` (runway/, downstream/, trends/, prices/, propagation_train.csv,
  wayback_coverage.csv, …)

## What to do next (from FUTURE_WORK.md, ranked)

1. **Accessory-lead study (H6)**: runway bag/shoe share → accessory search at
   ~9 months (the best new lead found), at seasonal frequency, overlap-robust.
   Cheapest high-value extension; data already on hand.
2. **Silhouette re-tag (H7)**: add shape to the vision schema, re-tag cached
   images, fit runway→retail lags — highest novelty (silhouette is the
   literature's top untested attribute).
3. **Measured color/category downstream (H8)**: extend 11_wayback_downstream
   to also read color+category off archived pages → test those channels on
   real retail data instead of the search proxy.
4. **Harden & commercialize the nowcast** (the retail-sales turning-point
   signal) — the strongest asset; see FUTURE_WORK.md §4 for who to pitch
   (alt-data brokers, retail analysts, trend vendors like Heuritech €12–35k/yr,
   fiber producers). Not fund money — it's data/forecasting/method/credibility.

## Discipline (non-negotiable — the whole point)

Pre-register in DECISIONS.md BEFORE any run against returns. Point-in-time via
known_date, always. Publish negatives. Never resurface H5. Selection-bias
guard on any best-of-sweep trade claim.
