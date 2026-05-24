#!/usr/bin/env bash
# VRAM health check for the bishop-loop sweep. Fails when Ollama reports
# Skippy is loaded but its size_vram is zero — the silent CPU-fallback
# fingerprint that wasted the May 22 run.
#
# When the alert condition fires, the script BOTH writes to the log AND
# delivers a desktop notification. The notification path is the
# load-bearing part: a check that doesn't notify is worse than none.
#
# Install:
#   crontab -e
#   */15 * * * * /home/alan/bishop-loop-experiment-3/scripts/vram_watchdog.sh
#
# Manual verification:
#   bash scripts/vram_watchdog.sh --simulate-fail
#       -> should produce a desktop notification AND append a [FAIL] line
#       -> if you don't see a popup, the alert path is broken; fix that
#          before launching the long run.

set -u

SKIPPY_MODEL="${SKIPPY_MODEL:-qwen3-coder:30b}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
LOG_FILE="${WATCHDOG_LOG:-/home/alan/bishop-loop-experiment-3/scripts/vram_watchdog.log}"
UID_NUM="$(id -u)"

# notify-send invoked from cron has no inherited DBUS / DISPLAY; set them
# so the popup actually reaches the desktop session.
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/${UID_NUM}/bus}"
export DISPLAY="${DISPLAY:-:0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${UID_NUM}}"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

log() {
    echo "$(ts) $*" >> "$LOG_FILE"
}

notify_critical() {
    local title="$1"
    local body="$2"
    notify-send -u critical -t 0 -a "bishop-loop watchdog" "$title" "$body" \
        2>>"$LOG_FILE" \
        || log "[warn] notify-send failed; alert may not have reached desktop"
}

alert_and_exit() {
    local body="$1"
    log "[FAIL] $body"
    notify_critical "Bishop-loop VRAM watchdog" "$body"
    exit 2
}

if [[ "${1:-}" == "--simulate-fail" ]]; then
    alert_and_exit "SIMULATED failure — verify you saw a desktop popup."
fi

# Query /api/ps. A server outage during an unattended run is also a hard
# fail worth alerting on.
ps_json="$(curl -fsS --max-time 10 "$OLLAMA_HOST/api/ps" 2>>"$LOG_FILE")" \
    || alert_and_exit "ollama /api/ps unreachable at $OLLAMA_HOST"

# Find a loaded entry whose name or model field matches SKIPPY_MODEL.
# .models[].name and .models[].model both exist; either may carry the tag.
size_vram="$(printf '%s' "$ps_json" \
    | jq -r --arg m "$SKIPPY_MODEL" \
        '.models[]? | select(.name == $m or .model == $m) | .size_vram' \
    | head -n 1)"

if [[ -z "$size_vram" ]]; then
    # Skippy not currently loaded. Between iterations this can briefly happen;
    # in practice during an active sweep the model is resident for the whole
    # 90-minute run. Log but do not alert — alerting on idle would train the
    # user to ignore the popup. The size_vram == 0 case below is the real
    # silent-failure fingerprint we care about.
    log "[ok-idle] $SKIPPY_MODEL not currently loaded (no active sweep?)"
    exit 0
fi

if [[ "$size_vram" == "0" || "$size_vram" == "null" ]]; then
    alert_and_exit "$SKIPPY_MODEL is loaded but size_vram=$size_vram (CPU fallback)."
fi

log "[ok] $SKIPPY_MODEL size_vram=$size_vram"
exit 0
