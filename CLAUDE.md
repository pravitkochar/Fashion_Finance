# Fashion Industry Event Studies — Master Project

## Goal
Three independent event studies of luxury parent stocks vs. fashion-industry 
events. Three Excel + three Word doc deliverables.

## Project root
~/Documents/Claude/Project/Fashion Thing/

## Subprojects (execution order)
1. /brief_2_met_gala — Met Gala red-carpet effect (FIRST)
2. /brief_1_cd_appointments — Creative-director appointments (SECOND)
3. /brief_4_fashion_week — Fashion-week aggregate effect (THIRD)

## Run order
Strict sequence Brief 2 → 1 → 4. Do not start a brief until prior is at 
Definition of Done OR has hit a hard stop and been retried once with 
relaxed thresholds.

## Failure cascade
If a brief hits a hard stop: retry ONCE with relaxed minimum-event 
threshold (50% of original). If still failing, skip to next brief. 
Write skipped status to /reports/skipped.json. Continue.

## Shared infrastructure (DO NOT re-scrape)
- /data/prices_raw.csv (from Phase 1)
- /data/confounders.csv (from Phase 1)
- /scripts/lib_event_study.py (build in Brief 2, reuse in 1+4)
- /scripts/lib_excel.py (build in Brief 2, reuse in 1+4)
- /scripts/lib_doc.py (build in Brief 2, reuse in 1+4)

## Universe (locked, all 3 briefs)
14 listed parents:
- Conglomerates: MC.PA, KER.PA, CPRI, TPR, COH (2000-2017), PVH
- Pure-plays: RMS.PA, BRBY.L, 1913.HK, BC.MI, MONC.MI, BOSS.DE, RL, SFER.MI, TOD.MI

Local index map: MC.PA/KER.PA/RMS.PA → ^FCHI; BRBY.L → ^FTSE; 
1913.HK → ^HSI; BC.MI/MONC.MI/SFER.MI/TOD.MI → FTSEMIB.MI; 
BOSS.DE → ^GDAXI; CPRI/TPR/COH/PVH/RL → ^GSPC.

## Cross-cutting IN
- Event window -30 to +30 trading days
- Raw + abnormal returns vs. local index
- Three statistical tests (aggregate t-stat, median brand effect, visual)
- Excel + Word doc per brief

## Cross-cutting OUT
- Briefs beyond 1, 2, 4
- Cross-brief meta-analysis (Phase 2)
- Re-scraping Phase 1 prices
- Additional benchmarks beyond local index
- Charts beyond per-brief specs
- Statistical tests beyond the three specified
- Currency conversion (use local currency throughout)

## Token discipline
- Plan-first, then auto-execute. ONE approval gate before all three.
- One announcement per phase per brief: "Brief X — Starting Phase N."
- Scripts in subproject /scripts. Run as subprocesses.
- logging.INFO only. No print().
- File writes idempotent.
- Do NOT commit anything.

## Anti-scope-creep
- Questions extending beyond 7 phases of any brief → STOP, ask
- Do NOT improve methodology mid-run
- Negative result (no signal) is acceptable — write up honestly

## Workflow
1. Read this + all 3 brief CLAUDE.md files
2. Propose 5-bullet execution plan covering all 3 briefs
3. Wait for "go"
4. Execute Brief 2 → 1 → 4 per failure-cascade rules
5. Final report: status of all three (DONE / SKIPPED / FAILED)
