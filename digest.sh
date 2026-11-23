#!/bin/bash
# Fantasy digest: digest.sh <waivers|sunday|tnf> [ET-hour-guard]
# Cron fires at both the EDT and EST UTC times; the guard keeps only the one matching Eastern time.
set -uo pipefail
KIND=$1; WANT_HOUR=${2:-}
DIR=$(dirname "$(readlink -f "$0")")
cd "$DIR" || exit 1
if [[ -n $WANT_HOUR && $(TZ=America/New_York date +%-H) != "$WANT_HOUR" ]]; then exit 0; fi
set -a; source .env; set +a
STAMP=$(TZ=America/New_York date +%Y-%m-%d_%H%M)
OUT=reports/${STAMP}_${KIND}.md
LOG=reports/digest.log
PY="$DIR/.venv/bin/python -I"
WEB_URL=${FANTASY_WEB_URL:-http://localhost:8095}   # tap the push -> opens the report

case $KIND in
  waivers) TITLE="🏈 Waiver picks"
    TASK="Waiver digest for this week's claims. Give the top 3 adds for MY roster (rest-of-season value, bye/roster holes), each with the drop candidate and a FAAB bid range (or priority advice). Include any streamer worth adding at QB/TE/DEF/K for next week." ;;
  sunday) TITLE="🏈 Lineup check"
    TASK="Final Sunday start/sit check for this week. Check every starter in my lineup for injury status (use web search for today's inactives/game-time decisions), bye weeks, empty slots, and clearly better bench options. Only list concrete lineup CHANGES I should make; if none, say the lineup looks good." ;;
  tnf) TITLE="🏈 TNF check"
    TASK="Thursday Night Football check. If none of my starters or close bench options play in tonight's game, make line 1 exactly 'SUMMARY: SKIP' and nothing else. Otherwise give the start/sit call for those players tonight." ;;
  *) echo "usage: $0 waivers|sunday|tnf [hour]"; exit 2 ;;
esac

PROMPT="$TASK

Follow the fantasy MCP server's playbook. Pull fresh data with the fantasy tools; don't ask me questions.
Output format: line 1 must be 'SUMMARY: <phone-notification text, max 3 short lines separated by ' | '>'. Then a blank line and the full markdown report."

echo "$(date -u +%FT%TZ) start $KIND" >> "$LOG"
timeout 900 "$HOME/.local/bin/claude" -p "$PROMPT" \
  --allowedTools "mcp__fantasy__*" "WebSearch" "WebFetch" \
  --output-format text > "$OUT" 2>> "$LOG"
RC=$?
SUMMARY=$(grep -m1 '^SUMMARY:' "$OUT" | sed 's/^SUMMARY:[[:space:]]*//; s/ | /\n/g')

if [[ $RC -ne 0 || -z $SUMMARY ]]; then
  echo "$(date -u +%FT%TZ) FAIL $KIND rc=$RC" >> "$LOG"
  $PY -m fantasy.notify "⚠️ Fantasy digest failed" "$KIND digest failed (rc=$RC). See $DIR/$OUT" 2>> "$LOG"
  [[ -n ${KUMA_PUSH_URL:-} ]] && curl -fsS -m 10 "${KUMA_PUSH_URL}?status=down&msg=${KIND}-rc${RC}" > /dev/null
  exit 1
fi
if [[ $SUMMARY != SKIP* ]]; then
  $PY -m fantasy.notify "$TITLE" "$SUMMARY" "${WEB_URL}/#report=$(basename "$OUT")" 2>> "$LOG" || echo "$(date -u +%FT%TZ) push failed" >> "$LOG"
fi
[[ -n ${KUMA_PUSH_URL:-} ]] && curl -fsS -m 10 "${KUMA_PUSH_URL}?status=up&msg=${KIND}-ok" > /dev/null
echo "$(date -u +%FT%TZ) ok $KIND -> $OUT" >> "$LOG"
