# Brief 1 — Creative-Director Appointments

## Goal
Test whether listed luxury parents move when an owned brand appoints a new 
creative director.

## Universe
14 parents + extended brand list:
- LVMH (MC.PA): Phase 1 flagships + Loewe, Celine, Givenchy, Fendi, Christian Dior
- Kering (KER.PA): Phase 1 flagships + Balenciaga, Alexander McQueen, Brioni, Boucheron

## Event scope — IN
- Top creative director appointments
- Women's RTW CD when distinct
- Men's CD when distinct
- Jewelry/watches CD when separately announced
- Both new appointments and replacements

## Event scope — OUT
- Internal promotions without title change
- Couture-only appointments
- Sub-brand appointments (e.g., head of accessories under unchanged CD)
- Acquisition-related CD inheritance

## Event date convention
Press release announcement date (NOT rumor date, NOT designer start date). 
If sources disagree by 1 day, take EARLIEST.

## pre_leaked flag
TRUE if BoF/WWD reported as rumor ≥7 days before official announcement.
UNKNOWN if rumor history can't be reliably determined (do NOT default FALSE).
FALSE if no rumor coverage in 7 days prior.

## Hard stops
- <60 events after scrape
- All major sources (LVMH/Kering IR, BoF, WWD) inaccessible
- Designer name fuzzy-match fails to converge

## Soft logs
- Source date conflict >1 day → take earliest, log
- Departing designer exit announced separately → treat as TWO events
- Source authority conflict (PR vs BoF) → use highest authority (PR=1, BoF=2)

## Definition of done
1. cd_appointments.csv ≥60 rows
2. events.csv valid for all events with prices
3. Excel: Overview + ≥6 parent tabs (incl. pre_leaked overlay chart)
4. Word doc: 7 sections + ≥4 charts
5. findings.json incl. pre_leaked TRUE vs FALSE cohort

## Full spec: see master prompt Part 4.
