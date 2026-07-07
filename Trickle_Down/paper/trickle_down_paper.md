# Does fashion trickle down? Measured propagation from runway to high street to fiber demand

**P. Kochar · Working paper · July 2026 · Data and code: github.com/pravitkochar/Fashion_Finance**

## Abstract

Verdict first: yes, fashion trickles down, and the lag is measurable — but trading it, at least the obvious way, does not work, and we can show both at the same standard of evidence.

We assembled a three-tier panel of the fashion supply chain: 26,838 runway looks from 22 houses across 23 seasons (FW2015–FW2026), each machine-tagged for fabric composition; 6,543 fabric labels read off archived Zara, H&M, ASOS and Uniqlo product pages recovered from the Internet Archive, covering 295 retailer-months back to January 2016; Google search interest for 22 material terms; and prices for 4 listed fiber suppliers plus cotton, crude and cattle futures. Every observation carries the date on which it became knowable. Nothing in this paper uses information from after that date.

Fitted on 2017–2022 only: a one-point rise in a material's runway share leads search interest in that material by 3–5 months (wool r = 0.69, viscose r = 0.59, cotton r = 0.50 at a 5-month lag, n = 78 months), and leads the same material's share of H&M and ASOS rack space by 4–12 months (best pair: ASOS wool, +5 months, r = 0.36). The runway-to-mill hop is weak (best r = 0.19) and we treat it as unproven. The propagation signal called clothing-store retail sales turning points 10–11 months ahead with 0.46 precision and 0.42 recall against an AR(3) baseline at 0.14 and 0.08; dropping the COVID reversals leaves 0.30 and 0.38. Three trading constructions were tested under pre-registered rules and all three failed: a continuous nowcast strategy (all 9 parameter combinations negative in walk-forward validation, best IR −0.39), a cross-sectional adoption factor (untestable — the archive supports depth on only two retailers), and an earnings-window event study (headline +3.1% per event, but n = 6, permutation p = 0.117, and a pre-event placebo window shows a LARGER effect, which kills the announcement story). The 2023–2025 test window remains sealed because nothing earned it.

## 1. The question

In March, Prada sends wool coats down a runway in Milan. The claim that this look works its way down — into Zara and H&M within a few seasons, into what people search for, eventually into order books at the mills that spin the fiber — is 127 years old. Veblen sketched it in 1899; Simmel formalized it in 1904; the fashion press repeats some version of it every season. What we could not find anywhere is a measured version: how many months, at what strength, for which materials.

That gap is the paper. The contribution is not a theory. It is a panel that did not previously exist, a set of fitted lags, one genuinely useful forecasting result, and three documented failures to convert any of it into excess returns.

## 2. Related work

Computer-vision work on fashion imagery has circled this question for a decade without landing on it. Vittayakorn, Yamaguchi, Berg and Berg (WACV 2015) built the first large-scale runway-to-street comparison; their influence analysis covers three hand-curated trends against 110 query images each, reads density plots visually, and fits no lags — the authors describe the exercise as preliminary. Chen et al. (ACM Multimedia 2015) correlate runway and street imagery within seasons. Al-Halah and Grauman's style-forecasting line (ICCV 2017; IEEE Trans. Multimedia 2020) is the closest antecedent; their 2020 influence model explicitly caps tested lags at eight weekly steps — two months — and models city-to-city influence, not cross-tier propagation. Choi, Lee and Jang (Fashion and Textiles, 2024) study one outerwear season in the Korean market and invoke the six-month fashion-calendar lead as an assumption; the words "lag" and "regression" do not appear in the paper.

Choi et al. also supply the most important caution in this literature: on standardized attribute frequencies, retailer best-sellers matched influencer outfits (MAE 0.48) far better than they matched runway collections (MAE 1.01), with silhouette attributes the exception that did propagate top-down. We therefore make no blanket trickle-down claim. Our results are conditional on the attribute we measure — fabric composition — and fabric may be precisely the attribute where top-down propagation survives, since it is priced into sourcing decisions months before sale.

Against this literature, the specific contribution here: fitted, multi-quarter, cross-tier propagation lags, estimated from measured (not assumed) retailer assortment history, under point-in-time discipline.

## 3. Data

Three tiers, one taxonomy: 12 canonical materials (cotton, denim, wool, cashmere, silk, leather, linen, viscose, polyester, nylon, elastane, technical) plus an OTHER bucket that is reported but excluded from signals. All shares are normalized within-garment; all derived rows carry a `known_date`.

**Tier 1 — runway.** 26,855 looks scraped from Vogue Runway for 22 houses (the LVMH, Kering, Prada and independent houses of the four fashion-week cities), womenswear RTW, FW2015 through FW2026 — 448 house-seasons, 85% of the target grid. 26,838 looks (99.9%) were tagged by vision models for fabric composition, dominant colors and garment category. Tagging used open vision models under free-tier quotas; 99.4% of tags came from a single model (Pixtral-12B), with three others contributing the remainder — per-look model attribution is logged, and pooling was accepted only after per-model share distributions were compared. Estimating fabric from a photograph is noisy at the look level. We rely on aggregation: a season vector averages roughly 1,200 looks, brands enter equal-weighted only when ≥5 looks are tagged, and the season's `known_date` is set days after the last show.

**Tier 2 — the high street, reconstructed.** The binding constraint on this entire literature is that nobody keeps a history of what fast fashion stocked. Our solution: the Internet Archive crawled retailer product pages for a decade, each snapshot timestamped, and those pages carry the legal fiber-content declaration ("87% cotton, 13% elastane"). We pulled 12,324 archived product pages and parsed 6,543 usable fabric labels across four retailers: H&M (115 months, 2,865 labels), ASOS (97 months, 2,185), Uniqlo (62 months, 1,493), Zara (21 months of assortment counts, zero labels — Zara's post-2017 pages render composition client-side, so the archived bytes do not contain it; ASSUMPTION-FREE coverage for Zara therefore ends in 2017). Coverage spans January 2016 to January 2026. A month enters the signal panel only with ≥30 parsed labels. The snapshot timestamp is the `known_date`; the reconstruction cannot look ahead because the archive cannot.

**Tier 3 — demand and prices.** Google Trends monthly interest for 22 material terms (3,058 series-months, z-scored against each term's own trailing 36 months); daily prices for Indorama Ventures, Toray, Reliance Industries and Lenzing plus cotton (CT), WTI crude (CL) and live cattle (LE) futures; the SPDR Retail ETF (XRT) and local equity indices as benchmarks; U.S. Census clothing-store retail sales (via FRED, series MRTSSM448USN) for the nowcasting test.

## 4. Method

Two rules did the real work in this project.

**Point-in-time.** Every table carries `known_date` and every signal computation passes through a single filter that discards rows not knowable at the evaluation date. A season is knowable days after its last show, an archived label at its snapshot timestamp, a Trends value at month-end. The one place this bit us — Zara's client-rendered pages — is disclosed above rather than patched with a proxy.

**Pre-registration.** Hypotheses, universes, parameter grids, rebalance cadence, cost assumptions (20 bp per side), and the evaluation split were written to a decision log before the code that used them ran; every subsequent amendment is a dated entry made before the affected run. The split: 2017–2022 for all fitting and tuning, walk-forward folds validating on 2020, 2021 and 2022 (expanding fit windows), and 2023–2025 sealed behind a mechanical guard — the backtester refuses the window unless a frozen-model entry exists in the log. It still refuses; see §6.

Propagation lags are fitted by lagged Pearson correlation on monthly series (season vectors step-forward-filled from their `known_date`), lag grid 0–12 months, best lag by maximum signed r, with an OLS beta at that lag; pairs with fewer than 12 overlapping months are excluded, not imputed.

## 5. Results I: the cascade, measured

**Runway → search interest (n = 78 months).** Eight of ten signal materials fit with positive lags. The center of the distribution is five months:

| material | lag (months) | r | beta |
|---|---|---|---|
| wool | 5 | 0.69 | 14.2 |
| viscose | 5 | 0.59 | 14.7 |
| linen | 5 | 0.54 | 738* |
| cotton | 5 | 0.50 | 58.9 |
| cashmere | 5 | 0.43 | 84.1 |
| leather | 5 | 0.39 | 19.3 |
| polyester | 3 | 0.36 | 11.5 |
| silk | 12 | 0.30 | 111.0 |

*Betas scale inversely with runway share variance; linen's runway share is tiny, so its beta is large and imprecise. Read the r column, not the beta column.

**Runway → rack space (22 fitted pairs).** Weaker, as expected — a retailer's mix moves for many reasons — but present, and consistent in direction with the search-interest hop: ASOS wool +5 months (r = 0.36, n = 40), H&M wool +5 (r = 0.34, n = 78), ASOS viscose +4 (r = 0.29), ASOS cotton +6 (r = 0.29), with the slower pairs (ASOS leather and polyester at +11 to +12 months) plausibly reflecting sourcing rather than reactive buying. Wool is the best-measured material on both hops, which matters for the current season: FW2026 runway wool share is 27.0%, +9.1 points against its trailing three-season mean — the largest emergence flag in the panel. On the fitted lags, that shift should be visible in search interest around September 2026 and on racks in the winter buy.

**Rack space → fiber suppliers.** The payoff hop is where the signal thins out: best pair Toray/technical at +6 months, r = 0.19; the commodity reference pairs sit at r ≤ 0.15. Sixty months of supplier data against a noisy demand proxy is not enough, and we say so rather than promote a 0.19. UNPROVEN.

## 6. Results II: three ways it does not trade, one way it forecasts

Every construction below was specified in the decision log before its first run against returns.

**Continuous nowcast (H2).** Tilt toward fiber suppliers when downstream demand for their material runs hot. All nine pre-registered parameter combinations produced negative information ratios in walk-forward validation — best −0.39, on measured retailer data; the Google-Trends proxy variant was worse. No cell was promoted; no model was frozen.

**Cross-sectional adoption factor (H1).** Rank retailers by how fast they converge to the prior runway season; long the fast, short the slow. The archive's verdict: at no rebalance date between 2018 and 2022 do more than two retailers clear the data floors simultaneously. A two-name cross-section is a pair trade, not a factor. H1 is unfalsifiable on free archival data and remains a live-only paper track — reported as a coverage result, not evidence for or against the economics.

**Earnings-window event study (H4).** The alternative-data literature says slow signals pay at disclosure: satellite parking-lot counts earn 3.4–4.8% per event inside three-day earnings windows (Katona et al., JFQA 2025; Froot et al. 2017 with consumer data). We pre-registered the same template: year-over-year cascade-alignment deltas, above/below-median long/short, held [−1,+1] days around announcements, 24-cell robustness grid. The headline cell reads +3.07% per event with a 67% hit rate — and fails every check behind it: n = 6 events (free earnings-calendar coverage reaches only four of our names), t = 0.87, permutation p = 0.117, and the pre-event placebo window [−10,−8] shows a larger spread (+7.2%, t = 4.07) than the event window itself. Whatever moves these names is not the announcement. The adequately powered cells (n = 35–37, supplier material-demand signal) are signed the wrong way (t ≈ −2.1). H4 is a null, and the placebo makes it a clean one. NULL.

**The forecasting result.** The same composite that fails to trade calls macro turning points. Against twelve peaks and troughs in the year-over-year growth of U.S. clothing-store retail sales (2016–2022), the runway-weighted trends composite leads by 10–11 months with precision 0.46 and recall 0.42; an AR(3) baseline manages 0.14 and 0.08 at those horizons, and persistence manages nothing. Dropping the four COVID reversals — the honest stress test, since 2020 supplies easy hits — leaves precision 0.30, recall 0.38 on eight turning points (3 called). Level correlation at those leads is approximately zero (−0.15): this is a turning-point indicator, not a tracker. Eight ex-COVID events is thin, and we treat the result as promising rather than proven; it is, however, exactly the profile that survives out-of-sample in the nowcasting literature, where value concentrates at inflections rather than in average error.

## 7. Limitations

Four retailers, one of them label-less after 2017, all fast-fashion, skewed to the US/EU sites the Archive crawled — the "high street" here is a specific slice of it. Vision-tagged fabric shares are estimates; 99.4% single-model tagging means a systematic model bias would propagate, though it would have to correlate with future retail assortment to fake our lags. Google Trends is a relative index with vintage effects we only partly control by z-scoring. The multiple-testing surface across the whole project is wide; the decision-log discipline bounds it (every grid cell is published, headline cells were named in advance), but a reader should still weight the pre-registered comparisons above anything exploratory. And per Choi et al., attribute-conditionality is not a caveat but a finding: fabric propagates on our data; silhouettes propagated on theirs; best-seller styling appears to flow from influencers, not runways. Trickle-down survives as a claim about specific attributes, not about fashion.

## 8. Conclusion

The 127-year-old theory is measurable, and measured: runway fabric shifts lead consumer search by roughly five months and fast-fashion assortment by four to twelve, with wool the cleanest thread through every tier. The same measurements refuse, three times and under rules set in advance, to become a trading strategy — coverage kills one construction, validation kills another, and a placebo kills the third. What survives is a 10–11 month early-warning indicator for apparel retail turning points and a reproducible method: the Internet Archive as a point-in-time record of commercial assortment is, as far as we can tell, unused in this literature, and it generalizes to any retail category whose product pages disclose composition, ingredients or specifications.

The pipeline continues to run nightly. The forward track accumulates; the sealed window stays sealed until something earns it.

## References

Al-Halah, Z., Stiefelhagen, R., Grauman, K. (2017). Fashion Forward: Forecasting Visual Style in Fashion. *ICCV 2017*.
Al-Halah, Z., Grauman, K. (2020). From Paris to Berlin: Discovering Fashion Style Influences Around the World. *IEEE Trans. Multimedia* (arXiv:2011.09663).
Chen, K., et al. (2015). Who are the Devils Wearing Prada in New York City? *ACM Multimedia 2015*.
Choi, Y., Lee, J., Jang, J. (2024). Quantitative analysis of fashion trend propagation. *Fashion and Textiles* 11:30.
Froot, K., Kang, N., Ozik, G., Sadka, R. (2017). What do measures of real-time corporate sales say about earnings surprises and post-announcement returns? *J. Financial Economics* 125(1).
Katona, Z., Painter, M., Patatoukas, P.N., Zeng, J. (2025). On the capital market consequences of big data: Evidence from outer space. *J. Financial and Quantitative Analysis*.
Simmel, G. (1904). Fashion. *International Quarterly* 10.
Veblen, T. (1899). *The Theory of the Leisure Class*.
Vittayakorn, S., Yamaguchi, K., Berg, A.C., Berg, T.L. (2015). Runway to Realway: Visual Analysis of Fashion. *WACV 2015*.

*Methods appendix, decision log (DECISIONS.md), all per-cell robustness tables and the full pipeline are in the public repository. Derived statistics only; no runway or retailer imagery is redistributed.*

## Appendix A: full tables

**A1. Runway → retailer rack share, all 22 fitted pairs (train window).**

| retailer | material | lag (mo) | r | n |
|---|---|---|---|---|
| asos | wool | 5 | 0.36 | 40 |
| hm | wool | 5 | 0.34 | 78 |
| asos | leather | 11 | 0.31 | 40 |
| asos | viscose | 4 | 0.29 | 40 |
| asos | cotton | 6 | 0.29 | 40 |
| asos | technical | 4 | 0.25 | 40 |
| asos | polyester | 11 | 0.25 | 40 |
| hm | polyester | 12 | 0.23 | 75 |
| hm | cashmere | 11 | 0.22 | 76 |
| hm | linen | 8 | 0.18 | 78 |
| hm | denim | 9 | 0.18 | 78 |
| asos | elastane | 11 | 0.16 | 40 |
| asos | denim | 3 | 0.15 | 40 |
| hm | leather | 12 | 0.15 | 75 |
| asos | nylon | 4 | 0.13 | 40 |
| asos | linen | 0 | 0.11 | 40 |
| hm | viscose | 4 | 0.11 | 78 |
| hm | silk | 6 | 0.09 | 78 |
| hm | cotton | 6 | 0.07 | 78 |
| hm | elastane | 4 | 0.02 | 78 |
| hm | nylon | 12 | -0.03 | 75 |
| hm | technical | 6 | -0.04 | 78 |

**A2. Turning-point scorecard by lead (dev window, 12 turning points; precision / recall).**

| lead (mo) | cascade composite | measured-mix composite | AR(3) |
|---|---|---|---|
| 1 | 0.27 / 0.25 | 0.33 / 0.08 | 0.31 / 0.33 |
| 2 | 0.27 / 0.25 | 0.00 / 0.00 | 0.22 / 0.17 |
| 3 | 0.18 / 0.17 | 0.67 / 0.17 | 0.20 / 0.08 |
| 4 | 0.18 / 0.17 | 0.67 / 0.17 | 0.25 / 0.08 |
| 5 | 0.00 / 0.00 | 0.67 / 0.17 | 0.14 / 0.08 |
| 6 | 0.18 / 0.17 | 0.00 / 0.00 | 0.33 / 0.17 |
| 7 | 0.18 / 0.17 | 0.00 / 0.00 | 0.33 / 0.08 |
| 8 | 0.27 / 0.25 | 0.00 / 0.00 | 0.29 / 0.17 |
| 9 | 0.27 / 0.25 | 0.33 / 0.08 | 0.22 / 0.17 |
| 10 | 0.46 / 0.42 | 0.67 / 0.17 | 0.14 / 0.08 |
| 11 | 0.46 / 0.42 | 0.67 / 0.17 | 0.14 / 0.08 |
| 12 | 0.27 / 0.25 | 0.33 / 0.08 | 0.33 / 0.08 |

**A3. H4 event study — every grid cell with n ≥ 10 (per-event L/S spread; dev window).**

| cell | spread | t | n |
|---|---|---|---|
| median/[-1,+1]/material_demand_yoy/xrt | +0.0000 | -1.14 | 37 |
| median/[0,+2]/material_demand_yoy/xrt | +0.0000 | -2.11 | 37 |
| median/[-1,+1]/material_demand_yoy/local | +0.0000 | -1.63 | 36 |
| median/[0,+2]/material_demand_yoy/local | +0.0000 | -2.11 | 35 |
| median/[-1,+1]/adoption_yoy/xrt | +0.0000 | 0.11 | 10 |
| median/[-1,+1]/adoption_yoy/local | +0.0000 | 0.18 | 10 |
| median/[0,+2]/adoption_yoy/local | +0.0000 | 0.83 | 10 |

Permutation placebo (headline cell): one-sided p = 0.117. Pre-event window [−10,−8]: spread +0.0722, t = 4.07 — larger than the event window itself, refuting an announcement-driven interpretation.
