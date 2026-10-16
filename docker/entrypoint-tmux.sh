#!/usr/bin/env bash
# entrypoint-tmux.sh — TUI-mode variant: agents run as INTERACTIVE claude
# sessions in tmux windows, fed missions and nudges by a driver loop.
#
# Compare against the headless (-p) variant: this one keeps each agent's
# session ALIVE (true back-and-forth in one context), at the cost of context
# growth over time and TUI-fragility. Stdout is preserved by tailing the
# driver log; per-window output stays inspectable via tmux inside the
# container.
set -uo pipefail

log() { printf '[sapper-tmux] %s\n' "$*"; }
die() { printf '[sapper-tmux] FATAL: %s\n' "$*" >&2; exit 1; }

[[ -n "${BENCHMARK_BASE_URL:-}" ]] || die "BENCHMARK_BASE_URL is not set"
[[ -n "${BENCHMARK_TOKEN:-}" ]] || die "BENCHMARK_TOKEN is not set"
: "${ANTHROPIC_BASE_URL:?set ANTHROPIC_BASE_URL}"
: "${ANTHROPIC_AUTH_TOKEN:?set ANTHROPIC_AUTH_TOKEN}"
export ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_TELEMETRY=1 \
       DISABLE_ERROR_REPORTING=1 DISABLE_AUTOUPDATER=1 IS_SANDBOX=1

mkdir -p "$HOME/.claude"
cat > "$HOME/.claude.json" <<JSON
{"hasCompletedOnboarding": true, "theme": "dark", "hasTrustDialogAccepted": true}
JSON
[[ -f "$HOME/.claude/settings.json" ]] || \
  echo '{"permissions":{"defaultMode":"bypassPermissions"}}' > "$HOME/.claude/settings.json"

log "platform = $BENCHMARK_BASE_URL"
log "gateway  = $ANTHROPIC_BASE_URL"
log "model    = ${SAPPER_MODEL:-glm-5.3-flash[1m]} (interactive TUI x ${SAPPER_PARALLEL:-6})"

case "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        -H "BENCHMARK_TOKEN: $BENCHMARK_TOKEN" \
        "$BENCHMARK_BASE_URL/openapi/v1/challenges" || true)" in
  2*) log "platform reachable" ;;
  *)  die "cannot reach the challenges API" ;;
esac

ROOT="${SAPPER_ROOT:-/work/runs}"
mkdir -p "$ROOT"

start_driver_window() {
  tmux new-window -d -t sapper-tui -n supervisor "bash /opt/sapper/docker/tmux-drive.sh 2>&1 | tee -a $ROOT/drive.err"
}

# detached fleet session; window 0 becomes the supervisor
tmux new-session -d -s sapper-tui -n boot "exec sleep infinity"
start_driver_window
tmux kill-window -t sapper-tui:boot 2>/dev/null
log "tmux session 'sapper-tui' up (supervisor driving)"

# watchdog: stream logs for the platform AND resurrect the driver if it dies.
# The driver itself is idempotent (adopts existing windows), so a respawn
# never duplicates work.
touch "$ROOT/drive.log" "$ROOT/drive.err"
tail -F -n0 "$ROOT/drive.log" "$ROOT/drive.err" &
TAIL_PID=$!
while true; do
  sleep 30
  if ! tmux has-session -t sapper-tui 2>/dev/null; then
    log "WATCHDOG: tmux session gone — recreating"
    tmux new-session -d -s sapper-tui -n boot "exec sleep infinity"
    start_driver_window
    tmux kill-window -t sapper-tui:boot 2>/dev/null
  elif ! tmux list-windows -t sapper-tui -F '#W' 2>/dev/null | grep -q '^supervisor$'; then
    log "WATCHDOG: supervisor window gone — respawning driver"
    start_driver_window
  fi
done
