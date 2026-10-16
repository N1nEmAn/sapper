#!/usr/bin/env bash
# sapper-entrypoint — container start: validate env, then drive TSecBench.
#
# ONE-SHOT match rules (Throne Protocol online round): a single evaluation,
# 8h task limit, model rate-limits are NOT retried by the platform — so this
# script and the sapper loops below degrade and continue instead of dying.
set -uo pipefail

log() { printf '[sapper] %s\n' "$*"; }
die() { printf '[sapper] FATAL: %s\n' "$*" >&2; exit 1; }

# ---- 1. required platform env ---------------------------------------------
[[ -n "${BENCHMARK_BASE_URL:-}" ]] || die "BENCHMARK_BASE_URL is not set (platform-injected)"
[[ -n "${BENCHMARK_TOKEN:-}" ]] || die "BENCHMARK_TOKEN is not set (platform-injected)"

# ---- 2. model gateway env --------------------------------------------------
: "${ANTHROPIC_BASE_URL:?ANTHROPIC_BASE_URL not set (e.g. http://open.bigmodel.cn.tsecbench.gw/api/anthropic)}"
: "${ANTHROPIC_AUTH_TOKEN:?ANTHROPIC_AUTH_TOKEN not set (the provider API key)}"
export ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN

# hosted mode has no public internet except the model gateway
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export DISABLE_TELEMETRY=1
export DISABLE_ERROR_REPORTING=1
export DISABLE_AUTOUPDATER=1
export IS_SANDBOX=1
export SAPPER_RETRY_MODEL="${SAPPER_RETRY_MODEL:-3}"

# ---- 3. non-interactive model CLI state -----------------------------------
mkdir -p "$HOME/.claude"
cat > "$HOME/.claude.json" <<JSON
{"hasCompletedOnboarding": true, "theme": "dark", "hasTrustDialogAccepted": true}
JSON
if [[ ! -f "$HOME/.claude/settings.json" ]]; then
  echo '{"permissions":{"defaultMode":"bypassPermissions"}}' > "$HOME/.claude/settings.json"
fi

# ---- 4. preflight ----------------------------------------------------------
log "platform = $BENCHMARK_BASE_URL"
log "gateway  = $ANTHROPIC_BASE_URL"
log "model    = ${SAPPER_MODEL:-glm-5.3-flash[1m]} (retries: $SAPPER_RETRY_MODEL)"
case "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        -H "BENCHMARK_TOKEN: $BENCHMARK_TOKEN" \
        "$BENCHMARK_BASE_URL/openapi/v1/challenges" || true)" in
  2*) log "platform reachable" ;;
  *)  die "cannot reach $BENCHMARK_BASE_URL/openapi/v1/challenges (check BENCHMARK_TOKEN / gateway)" ;;
esac

log "model CLI smoke test…"
if ! printf 'reply with the single word: ok' \
     | claude -p --model "${SAPPER_MODEL:-glm-5.3-flash[1m]}" >/tmp/smoke.txt 2>/tmp/smoke.err; then
  log "WARNING: model CLI smoke test failed; continuing (bench loops will retry)"
  sed -n '1,5p' /tmp/smoke.err | sed 's/^/  /'
else
  log "model CLI ok: $(head -c 60 /tmp/smoke.txt)"
fi

# ---- 5. run the benchmark loop --------------------------------------------
# 8h task limit; keep a small safety margin. bench loops over every
# unfinished challenge and re-visits solved-later ones across rounds.
ROOT="${SAPPER_ROOT:-/work/runs}"
TOTAL="${SAPPER_TOTAL_MINUTES:-470}"
PER="${SAPPER_MINUTES_PER_CHALLENGE:-9}"
mkdir -p "$ROOT"
log "starting: sapper bench --root $ROOT --minutes $TOTAL (per-challenge ${PER}m, parallel ${SAPPER_PARALLEL:-3})"

exec sapper bench \
  --root "$ROOT" \
  --minutes "$TOTAL" \
  --minutes-per-challenge "$PER" \
  --max-steps "${SAPPER_MAX_STEPS:-10}" \
  --parallel "${SAPPER_PARALLEL:-3}" \
  --model "${SAPPER_MODEL:-glm-5.3-flash[1m]}" \
  --skip-permissions
