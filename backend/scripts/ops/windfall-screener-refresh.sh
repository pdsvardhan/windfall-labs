#!/usr/bin/env bash
# /opt/homeserver/scripts/windfall-screener-refresh.sh   (source of truth: backend/scripts/ops/ in the repo)
# Monthly refresh of the screener.in fundamentals store (iter-206, to-do #971). Cron: 03:00 on the 5th,
# May-September (annual results land May-Aug; a refresh outside that window adds nothing — iter-201).
#
# Why this shape:
#  - A refresh OVERWRITES history (EPS rebased for later splits, ~5 real restatements per 40 names), so
#    the live store is copied to data/snapshots/screener_fundamentals-<date>.duckdb BEFORE anything runs.
#  - The ingest runs on a scratch COPY (fresh html cache, so pages are re-fetched), never on the live
#    file: the api opens the store read-only on every request and a writer would lock it for the ~1 h
#    the run takes. When it is done the finished file is moved over the live one — an atomic rename, so
#    no request ever sees a half-written store and the api does not need to stop.
#  - If more than 5% of names fail (rate limiting, a screener.in change), the live store is left
#    untouched and the run is logged FAILED; the snapshot is kept either way.
#
# Known limits: it refreshes the names already in the store, so a company listed since the last
# extension never enters it (extend with `python -m windfall.data.screener_fundamentals --symbols-file ...`);
# failures are logged, not alerted; snapshots accumulate (about 15 MB each) with no retention.
#
# DRY_RUN=1  -> run on LIMIT names (default 5) into scratch, report, swap nothing.
set -u
APP=/mnt/storage/websites/windfall-labs
DATA="${WINDFALL_REFRESH_DATA:-$APP/backend/data}"   # override only for tests
LIVE="$DATA/screener_fundamentals.duckdb"
SNAPDIR="$DATA/snapshots"
LOG="$DATA/screener-refresh.log"
PY="$APP/backend/.venv/bin/python"
MAX_FAIL_PCT=5
LIMIT="${LIMIT:-5}"

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# two overlapping runs would each copy the live file and the later swap would win
exec 9>/tmp/windfall-screener-refresh.lock
flock -n 9 || { log "SKIPPED: another refresh is running"; exit 0; }

mkdir -p "$SNAPDIR"
STAMP="$(date +%F)"
SNAP="$SNAPDIR/screener_fundamentals-$STAMP.duckdb"
[ -e "$SNAP" ] && SNAP="$SNAPDIR/screener_fundamentals-$STAMP-$(date +%H%M).duckdb"

log "=== screener refresh start (dry_run=${DRY_RUN:-0}) ==="
if [ ! -s "$LIVE" ]; then log "FAILED: live store missing at $LIVE"; exit 1; fi
if [ "${DRY_RUN:-0}" != "1" ]; then
  cp "$LIVE" "$SNAP" || { log "FAILED: could not snapshot to $SNAP"; exit 1; }
  log "snapshot -> $SNAP ($(du -h "$SNAP" | cut -f1))"
fi

SCR="$(mktemp -d /tmp/windfall-screener-refresh.XXXXXX)"
trap 'rm -rf "$SCR"' EXIT
cp "$LIVE" "$SCR/screener_fundamentals.duckdb"

# every name already in the store, except the financials it excludes by design
PYTHONPATH="$APP/backend" WINDFALL_DATA_DIR="$SCR" "$PY" - "$SCR/symbols.csv" <<'EOF'
import csv, sys, duckdb, os
con = duckdb.connect(os.path.join(os.environ["WINDFALL_DATA_DIR"], "screener_fundamentals.duckdb"), read_only=True)
rows = con.execute("SELECT DISTINCT ticker FROM fundamentals_history "
                   "WHERE confidence NOT IN ('excluded-financial') ORDER BY 1").fetchall()
with open(sys.argv[1], "w", newline="") as f:
    w = csv.writer(f); w.writerow(["symbol"])
    for (t,) in rows:
        w.writerow([t.replace(".NS", "")])
print(len(rows))
EOF
TOTAL=$(($(wc -l < "$SCR/symbols.csv") - 1))
if [ "${DRY_RUN:-0}" = "1" ] || [ -n "${SUBSET:-}" ]; then
  { head -1 "$SCR/symbols.csv"; tail -n +2 "$SCR/symbols.csv" | shuf -n "${SUBSET:-$LIMIT}"; } > "$SCR/s.csv"
  mv "$SCR/s.csv" "$SCR/symbols.csv"; TOTAL=${SUBSET:-$LIMIT}
fi
log "refreshing $TOTAL names on a scratch copy"

PYTHONPATH="$APP/backend" WINDFALL_DATA_DIR="$SCR" "$PY" -u -m windfall.data.screener_fundamentals \
  --symbols-file "$SCR/symbols.csv" --cross-check > "$SCR/ingest.out" 2>&1
RC=$?
SUMMARY="$(grep -m1 '^requested' "$SCR/ingest.out" || echo 'no summary line')"
FAILED=$(printf '%s' "$SUMMARY" | sed -n "s/.*'failed': \([0-9]*\).*/\1/p"); FAILED=${FAILED:-$TOTAL}
log "ingest rc=$RC :: $SUMMARY"

LIMIT_FAIL=$(( TOTAL * MAX_FAIL_PCT / 100 ))
if [ "$RC" -ne 0 ] || [ "$FAILED" -gt "$LIMIT_FAIL" ]; then
  log "FAILED: $FAILED/$TOTAL names failed (limit $LIMIT_FAIL) — live store NOT replaced; snapshot kept"
  grep -i 'failed' "$SCR/ingest.out" | head -20 >> "$LOG"
  exit 1
fi
# 'failed' is not the only way to lose a name: the ingest deletes a ticker's rows and re-inserts them, and a
# page that now fails the store's self-check comes back 'quarantined', which the engine does not read. Compare
# how many tickers the engine CAN read (high/low) before and after. Deliberate tolerance: up to 2% (about 44
# tickers) may be lost without a failure, and the gate counts tickers, not periods per ticker.
USABLE=$(PYTHONPATH="$APP/backend" "$PY" - "$LIVE" "$SCR/screener_fundamentals.duckdb" <<'EOF'
import sys, duckdb
q = "SELECT count(DISTINCT ticker) FROM fundamentals_history WHERE confidence IN ('high','low')"
a = duckdb.connect(sys.argv[1], read_only=True).execute(q).fetchone()[0]
b = duckdb.connect(sys.argv[2], read_only=True).execute(q).fetchone()[0]
print(a, b)
EOF
)
set -- $USABLE
if [ "$#" -ne 2 ] || [ "$2" -lt $(( $1 * 98 / 100 )) ]; then
  log "FAILED: usable (high/low) tickers $USABLE (before after) - dropped more than 2%, live store NOT replaced"
  exit 1
fi
log "usable (high/low) tickers before/after: $1/$2"
if [ "${DRY_RUN:-0}" = "1" ]; then
  log "dry run ok — $FAILED failed of $TOTAL; nothing swapped"
  exit 0
fi
if [ -e "$SCR/screener_fundamentals.duckdb.wal" ]; then
  log "FAILED: scratch store still has a WAL (ingest did not close cleanly) — live store NOT replaced"
  exit 1
fi
mv -f "$SCR/screener_fundamentals.duckdb" "$LIVE.new" && mv -f "$LIVE.new" "$LIVE" \
  && log "live store replaced ($FAILED/$TOTAL failed)" || { log "FAILED: swap"; exit 1; }
log "=== screener refresh done ==="
