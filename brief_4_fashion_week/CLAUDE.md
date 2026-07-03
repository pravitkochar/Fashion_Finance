# Brief 4 — Fashion-Week Aggregate Effect

## Goal
Test whether the entire fashion week (not individual shows) moves listed 
luxury parents and the broader luxury sector. Includes local-index sanity 
check.

## Universe
14 listed parents + 4 local indices for sanity check (^FCHI, FTSEMIB.MI, 
^GSPC, ^FTSE).

## Event scope — IN
- Official women's RTW fashion week calendars only
- 4 cities: Paris (FHCM), Milan (Camera Moda), NY (CFDA/IMG), London (BFC)
- 2000-2025, both seasons
- 208 candidate weeks → ~1,000 (parent × week) events

## Event scope — OUT
- Couture week (Paris, Jan & July)
- Pre-fall trade shows
- Resort presentations
- Men's fashion week
- Off-schedule shows

## Brand-to-parent mapping (additive to Phase 1)
- Paris weeks: MC.PA (LV, Dior, Loewe, Celine, Givenchy, Fendi), KER.PA 
  (Saint Laurent, Balenciaga, Alexander McQueen), RMS.PA (Hermès)
- Milan: KER.PA (Gucci, Bottega), 1913.HK (Prada, Miu Miu), BC.MI, 
  MONC.MI, SFER.MI, MC.PA (Fendi when shown in Milan)
- NY: CPRI (Michael Kors), TPR (Coach), PVH (CK, Tommy), RL
- London: BRBY.L

## Event date convention
t=0 = first trading day on or after fashion week's official start date.
during_FW_AR = sum of abnormal returns from t=0 through last trading day 
within fw_end_date.

## Hard stops
- <150 fashion weeks scraped (75% of 208 target)
- Calendar body websites all inaccessible
- <700 (parent × week) events after explosion

## Soft logs
- Calendar URL changes → fall back to BoF/Vogue Runway
- Date discrepancy → use official calendar body, log
- Brand on calendar but not in universe → count in n_brands_showing only

## Definition of done
1. fw_calendar.csv ≥150 weeks
2. fw_events.csv ≥700 (parent × week) rows
3. Excel: Overview + 4 city tabs (NOT per-parent)
4. Word doc: 7 sections + index sanity check
5. findings.json: tests + city cohort + index sanity

## Full spec: see master prompt Part 5.
