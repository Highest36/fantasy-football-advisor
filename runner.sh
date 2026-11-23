#!/bin/bash
# SSH forced-command target for the fantasy web container (authorized_keys `command=`).
# Accepts only:  ask [session-uuid]   (question on stdin)  |  digest <waivers|sunday|tnf>
set -uo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$(readlink -f "$0")")" || exit 1
read -r -a ARGS <<< "${SSH_ORIGINAL_COMMAND:-}"
case "${ARGS[0]:-}" in
  ask)
    RESUME=()
    if [[ -n ${ARGS[1]:-} ]]; then
      [[ ${ARGS[1]} =~ ^[0-9a-f-]{36}$ ]] || { echo '{"is_error":true,"result":"bad session id"}'; exit 2; }
      RESUME=(--resume "${ARGS[1]}")
    fi
    Q=$(head -c 4000)
    [[ -n $Q ]] || { echo '{"is_error":true,"result":"empty question"}'; exit 2; }
    exec timeout 600 claude -p "$Q" "${RESUME[@]}" --output-format json \
      --allowedTools "mcp__fantasy__*" "WebSearch" "WebFetch" 2>/dev/null ;;
  digest)
    [[ ${ARGS[1]:-} =~ ^(waivers|sunday|tnf)$ ]] || { echo "bad digest kind"; exit 2; }
    ./digest.sh "${ARGS[1]}"; RC=$?
    tail -1 reports/digest.log; exit $RC ;;
  *) echo "not allowed"; exit 2 ;;
esac
