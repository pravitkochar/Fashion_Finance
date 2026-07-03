# Brief 2 — Met Gala Red-Carpet Effect

## Goal
Test whether the Met Gala moves listed luxury parents whose owned brands 
dressed marquee celebrities the night of the event.

## Universe
14 listed parents from master CLAUDE.md.

## Event scope — IN
- Met Gala only: first Monday of May 2000-2025, plus Sept 2021
- Skip 2020 (canceled)
- Panel structure: (parent × year) = one event row
- Tier A/B/C/N assigned per coverage

## Event scope — OUT
- Cannes, Oscars, Golden Globes
- Met after-parties, Costume Institute exhibition openings
- Brand-ambassador red carpets at non-Met events

## Tier definitions
- A: parent had Vogue's "Best Dressed" look of the night
- B: parent had a top-10-most-covered look (Vogue list + Lyst data)
- C: parent dressed someone but no top-10 look
- N: no parent dress credits that year

## Event date convention
t=0 = first trading day after Monday-night gala (typically Tuesday).

## Hard stops
- <300 panel rows after construction
- Vogue archive scrape blocked
- Tier-A subset <8 events (statistical-power floor)

## Soft logs
- Year with ambiguous tier-A → ambiguous_tier.csv, default no tier-A
- Brand worn by celeb not in universe → parent_ticker=NONE
- Lyst data missing → use Vogue rank only

## Definition of done
1. met_gala_panel.csv ≥300 rows
2. Tier-A subset ≥8 events
3. Excel: Overview + ≥6 parent tabs
4. Word doc: 7 sections + ≥4 embedded charts
5. findings.json with tier-A vs tier-N t-test result

## Full spec: see master prompt Part 3.
