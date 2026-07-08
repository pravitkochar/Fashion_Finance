# Trickle_Down — Future Work & Commercial Directions

Consolidated so a future session (or a future you) can build on this without
re-deriving anything. Everything here is EXPLORATORY unless it points at a
DECISIONS.md pre-registration. The core proven result and the honest nulls
live in the paper (paper/trickle_down_paper.md); this file is the "what next".

---

## 1. The channel matrix (exploratory screen, 2026-07-08)

Five channels × three questions. Probes in scripts/24_explore_channels.py and
scripts/25_prelim_matrix.py; numbers in reports/explore_channels.json and
reports/prelim_matrix.json. Every tradeable cell carries a selection-bias
guard (best-of-sweep p-value) so mining artifacts are caught.

| Channel | Q1 runway→retail | Q2 retail→supplier | Q3 tradeable |
|---|---|---|---|
| **Materials/fabric** | PROVEN (+4–12 mo, main study) | weak/spurious (r≤0.19; |t|=4.5 but wrong-signed) | NONE (fails guards) |
| **Color** | SIGNAL (|t|=3.9) but contemporaneous, not leading | WEAK (pigment eq |t|=2.4 +4mo, wrong-signed) | NONE (signal too sparse) |
| **Accessories (bags/shoes)** | **SIGNAL — leads accessory search +9 mo (|t|=3.2)** | WEAK (vs LVMH |t|=2.4 +7mo, wrong-signed) | NONE (best IR 2.4 DECK, selection-p 0.38) |
| **Silhouette (category proxy)** | WEAK (|t|=1.8, crude proxy) | UNTESTABLE (shape→no supplier) | NONE (selection-p 0.91) |
| **Prints/patterns** | UNTESTABLE (not tagged) | UNTESTABLE (no pure-play) | NONE (too sparse) |

**Two genuinely new forecasting leads worth a proper study:**
1. **Runway accessory-share → accessory search at ~9 months** — the most
   interesting lead found; test at seasonal frequency (monthly t is inflated
   by ffilled seasonal signals) with proper overlap-robust inference.
2. **Color emergence → color search** — real but contemporaneous; check
   whether any sub-slice (specific hues, dark/bright shift) actually leads.

**Every supplier link is weak or wrong-signed. Every tradeable cell is dead
once selection bias is corrected.** The paper's signature holds across all
five channels: information real, naive trade absent.

---

## 2. Data that would unlock the untestable cells

The gaps are all missing DATA, not missing method:
- **Downstream color + category**: the Wayback scraper (11_wayback_downstream)
  only read fabric composition. Extend it to also pull the product's color and
  category from the archived pages → unlocks Color Q1 and Accessories Q1 on
  MEASURED retail data instead of the search proxy.
- **Silhouette + print tags**: 02_tag_gemini tags material/color/category, not
  shape or print. Add both to the vision schema and re-tag the cached images
  (data/runway/images/ already downloaded) → unlocks Silhouette and Prints Q1.
  Per Choi et al. (2024) silhouette is the highest-potential untested attribute.
- **More retailers with deep archives**: H1 (adoption factor) stays untestable
  until ≥4 retailers have 60+ archive months. Zalando/Next/Uniqlo legacy
  domains are worth another Wayback pass.

## 3. Concrete next studies (ranked)

1. **Accessory-lead seasonal study** (pre-register as H6): runway bag/shoe
   share → accessory search, seasonal frequency, overlap-robust. Cheapest
   high-value extension; data already on hand.
2. **Silhouette re-tag + propagation** (H7): add shape to the vision schema,
   re-tag, fit runway→retail lags. Highest novelty, moderate cost (~$ vision).
3. **Measured color/category downstream** (H8): extend the Wayback scraper,
   rebuild mixes, re-test Color/Accessories Q1 on real retail data.
4. **The nowcast, hardened**: the 10–11 mo retail-sales turning-point signal
   is the strongest result — extend to more macro series (footwear, apparel
   imports, specific retailer revenue), formal turning-point stats, live track.

---

## 4. Commercialization directions

Honest framing: the project does NOT trade as a standalone strategy (proven,
three ways). So the value is as DATA / FORECASTING / METHOD / CREDIBILITY, not
as a fund. Ideas, best-first:

1. **Apparel-demand turning-point feed → retail analysts / macro & consumer
   funds / alt-data brokers.** The 10–11 mo lead on U.S. clothing-store retail
   sales, built entirely from public data, is the crown jewel. Even if it
   isn't a standalone trade, it's a real INPUT for anyone modelling apparel
   demand. Route: alt-data marketplaces (Neudata, Eagle Alpha, BattleFin),
   sell-side retail analysts, consumer-focused funds. Package as a monthly
   signal + methodology note. Anchor: niche alt-data feeds sell $10–100k/yr.

2. **Trend-lag intelligence → fashion forecasting vendors.** The measured
   runway→retail→search lags per material (and the new accessory +9 mo lead)
   are exactly the "trend intelligence" WGSN / Heuritech / Trendalytics /
   EDITED / First Insight sell. Route: license the lag dataset/method, or use
   it as a differentiated wedge to partner/get hired. Anchor: Heuritech listed
   €12–35k/yr per client; WGSN subscriptions similar.

3. **Material-demand nowcast → fiber producers & textile buyers.** Indorama,
   Lenzing, Toray (and big retail buying teams) plan capacity months ahead;
   a runway-derived early read on fiber demand mix is a planning input.
   Route: B2B pilot with a producer's demand-planning/strategy team.

4. **The reconstructed dataset itself.** 10 years of runway fabric tagging +
   Wayback-reconstructed retailer fabric-mix history is a novel dataset. Route:
   license to academics, trend vendors, or an alt-data broker as a raw feed.

5. **The method as a capability / consulting.** "Internet Archive as a
   point-in-time record of commercial assortment" generalizes to ANY retail
   category whose product pages disclose specs (ingredients, materials,
   components). Route: consulting builds for CPG/retail/e-commerce, or a
   productized "point-in-time competitive assortment" tool.

6. **The paper + site + deck as a credibility asset.** Publishing the novel
   finding (first fitted multi-quarter cross-tier lags) is a portfolio/door-
   opener for roles, clients, or a founding story — the honesty spine is itself
   a differentiator. Route: submit the paper, share the site, use in pitches.

**Reality check:** #1 and #2 are the realest near-term money; #3 is a longer
B2B sale; #5–#6 monetize the capability/credibility rather than the data. None
is "quant fund" money — the honest null closed that door and the paper says so.
