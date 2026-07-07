#!/bin/zsh
# Trickle_Down daily continuation job (launchd: com.pravit.trickledown.daily)
#
# Keeps the pipeline filling itself within free-tier quotas:
#   runway scrape (new shows) -> gemini tag backfill (quota-paced) ->
#   downstream snapshot -> trends refresh -> confounders -> prices ->
#   mixes -> propagation -> signals -> backtest -> dashboard
#
# Each step is independent: a failure logs and moves on (the pipeline is
# idempotent/resumable, so tomorrow's run picks up whatever today missed).

PROJ="$HOME/Developer/fashion-thing/Trickle_Down"
PY="$HOME/.venvs/trickle_down/bin/python"
LOG_DIR="$PROJ/reports/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_$(date +%Y%m%d).log"

cd "$PROJ" || exit 1
echo "===== daily run start $(date) =====" >> "$LOG"

step() {
  local name="$1"; shift
  echo "--- $name @ $(date +%H:%M:%S)" >> "$LOG"
  "$@" >> "$LOG" 2>&1
  echo "--- $name exit=$? " >> "$LOG"
}

step "01 runway"      "$PY" scripts/01_scrape_runway.py
if pgrep -f "02_tag_gemini" >/dev/null; then
  echo "--- 02 skipped: a tagger is already running (detached session)" >> "$LOG"
else
  step "02 tag mistral" "$PY" scripts/02_tag_gemini.py --provider mistral --limit 1200 --pace 1.2
  step "02 tag gemini"  "$PY" scripts/02_tag_gemini.py --limit 200 --model gemini-2.5-flash-lite
  step "02 tag groq"    "$PY" scripts/02_tag_gemini.py --provider groq --limit 100 --pace 15
fi
step "03 downstream"  "$PY" scripts/03_scrape_downstream.py
if pgrep -f "11_wayback_downstream" >/dev/null; then
  echo "--- 11 skipped: sweep already running (detached session)" >> "$LOG"
else
  step "11 wayback"   "$PY" scripts/11_wayback_downstream.py --max-requests 1200
fi
step "05 trends"      "$PY" scripts/05_google_trends.py
step "10 confounders" "$PY" scripts/10_confounders.py
step "04 mixes"       "$PY" scripts/04_material_mix.py
step "06 propagation" "$PY" scripts/06_propagation_lag.py
step "07 signals"     "$PY" scripts/07_signals.py
step "08 backtest"    "$PY" scripts/08_backtest.py --fetch
step "12 trends norm" "$PY" scripts/12_normalize_trends.py
step "13 fit"         "$PY" scripts/13_fit_propagation.py --folds
step "14 tune"        "$PY" scripts/14_tune_signals.py
step "19 event study" "$PY" scripts/19_event_study.py
step "20 nowcast"     "$PY" scripts/20_nowcast_census.py
step "09 dashboard"   "$PY" scripts/09_dashboard.py
step "16 site pages"  "$PY" scripts/16_site_pages.py
step "18 story"       "$PY" scripts/18_story_page.py

# surface a loud marker when CV clears zero — freezing stays a deliberate act
grep -q "READY TO FREEZE" "$LOG" && echo "*** CV CLEARED ZERO — review reports/cv_results.csv and freeze ***" >> "$LOG"

# keep 30 days of logs
find "$LOG_DIR" -name "daily_*.log" -mtime +30 -delete 2>/dev/null

echo "===== daily run end $(date) =====" >> "$LOG"
