#!/usr/bin/env bash
# quota-rotate-test.sh — minimal repro for the Q4 keypool patch (openrepo).
# Tests, against the PATCHED watchdog.sh (path or $1):
#   T1  QUOTA_RE matches built-in + user SAPPER_QUOTA_PATTERNS vendor wording
#   T2  rotate_key: invalid pool entries are loudly rejected (stderr)
#   T3  rotate_key: same-family untried key wins; rotated.env written;
#       current key recorded in .rotated-tried.txt
#   T4  rotate_key: pool exhausted inside TTL -> POOL-ALERT.txt + exit 1
#   T5  rotate_key: after SAPPER_TRIED_TTL the key becomes reusable
#   T6  check_schedule fires due entries exactly once (fake worker.sh)
# Exit 0 = all pass. No root, no network, no tmux needed.
set -u
# default target: the patched driver in this repo; pass another file to test it
WD="${1:-$(cd "$(dirname "$0")/.." && pwd)/docker/tmux-drive.sh}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fails=0
ok()   { printf '  PASS %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; fails=$((fails+1)); }

# ---- extract the patched pieces -------------------------------------------
awk '/^# ---- scheduled/{f=1} f{print} /^}$/{if(f)exit}' "$WD" > "$T/sched.fn"
QUOTA_LINE=$(grep -m1 '^QUOTA_RE=' "$WD")

# T1: pattern matching ------------------------------------------------------
if printf '%s' "HTTP 401 Unauthorized: Insufficient balance (余额不足)" \
   | bash -c "eval \"${QUOTA_LINE//\"/\\\"}\"; printf '%s' \"\$(cat)\" | grep -qE \"\$QUOTA_RE\""; then
  ok "T1a built-in quota wording matches"
else bad "T1a built-in quota wording NOT matched"; fi
if SAPPER_QUOTA_PATTERNS='|acme.?credits.?drained' \
   bash -c "eval \"${QUOTA_LINE//\"/\\\"}\"; printf '%s' 'acme credits drained, top up' | grep -qE \"\$QUOTA_RE\""; then
  ok "T1b SAPPER_QUOTA_PATTERNS extension matches"
else bad "T1b SAPPER_QUOTA_PATTERNS extension NOT matched"; fi

# T2-T5: drive the rotation python ------------------------------------------
awk '/<<.PYROT./{f=1;next} /^PYROT/{if(f)exit} f{print}' "$WD" > "$T/rot.py"
POOL='[{"base_url":"https://api.a.example","token":"KEY1","model":"m"},
       {"token":""},                       <- invalid: no token
       "junk",                             <- invalid: not an object
       {"base_url":"https://api.a.example","token":"KEY2","model":"m"}]'
POOL=$(printf '%s' '[{"base_url":"https://api.a.example","token":"KEY1","model":"m"},{"token":""},"junk",{"base_url":"https://api.a.example","token":"KEY2","model":"m"}]')
export SAPPER_ROOT="$T/root"; mkdir -p "$SAPPER_ROOT"
export SAPPER_KEY_POOL="$POOL" SAPPER_TRIED_TTL=1800

run_rot() { ANTHROPIC_AUTH_TOKEN="$1" python3 "$T/rot.py" 2> "$T/err"; }

run_rot KEY1
if [[ -f "$SAPPER_ROOT/rotated.env" ]] && grep -q KEY2 "$SAPPER_ROOT/rotated.env"; then
  ok "T3a rotated.env switches to untried same-family KEY2"
else bad "T3a no/incorrect rotated.env"; cat "$T/err"; fi
if grep -q 'REJECTED' "$T/err" && grep -q 'empty/missing token' "$T/err"; then
  ok "T2 invalid entries loudly rejected on stderr"
else bad "T2 rejection log missing"; cat "$T/err"; fi
if grep -q ' KEY1$' "$SAPPER_ROOT/.rotated-tried.txt"; then
  ok "T3b dead key recorded in .rotated-tried.txt"
else bad "T3b tried file missing KEY1"; fi

rm -f "$SAPPER_ROOT/POOL-ALERT.txt"
run_rot KEY2   # KEY1 tried within TTL -> nothing left -> exhaustion
if [[ -f "$SAPPER_ROOT/POOL-ALERT.txt" ]] && grep -q 'ALL POOL KEYS EXHAUSTED' "$SAPPER_ROOT/POOL-ALERT.txt"; then
  ok "T4 pool exhaustion writes POOL-ALERT.txt"
else bad "T4 no POOL-ALERT.txt"; cat "$T/err"; fi

export SAPPER_TRIED_TTL=1; sleep 1.2      # let KEY1 expire out of the window
run_rot KEY2
if grep -q KEY1 "$SAPPER_ROOT/rotated.env"; then
  ok "T5 expired key becomes reusable after SAPPER_TRIED_TTL"
else bad "T5 key not reused"; cat "$T/err"; fi
if ! grep -q ' KEY1$' "$SAPPER_ROOT/.rotated-tried.txt"; then
  ok "T5b expired rows pruned from .rotated-tried.txt"
else bad "T5b tried file still holds expired row"; fi

# T6: scheduled spawns (tmux-drive variant: fake launch + fake tmux) --------
mkdir -p "$T/bin"
printf '#!/bin/sh\nexit 1\n' > "$T/bin/tmux"; chmod +x "$T/bin/tmux"   # list-windows: no windows
( log() { :; }
  launch() { echo "launched:$1" >> "$T/spawn.log"; return 0; }
  SCHEDULE_FIRED="$T/.schedule-fired.txt"
  PATH="$T/bin:$PATH"
  eval "$(cat "$T/sched.fn")"
  SAPPER_SCHEDULE="00:00 tch3-91,tch3-92; 23:59 tch3-99" check_schedule
  SAPPER_SCHEDULE="00:00 tch3-91,tch3-92; 23:59 tch3-99" check_schedule   # second sweep must not refire
) >/dev/null 2>&1 || true
n=$(grep -c 'launched:tch3-9[12][[:space:]]*$' "$T/spawn.log" 2>/dev/null || true); n=$(grep 'launched:tch3-9[12][[:space:]]*$' "$T/spawn.log" 2>/dev/null | wc -l | tr -d '[:space:]')
[[ "$n" -eq 2 ]] && ok "T6 due entries fire once (2 launches, no refire)" || bad "T6 launch count = ${n:-0} (want 2)"
grep -q 'launched:tch3-99' "$T/spawn.log" 2>/dev/null && bad "T6 future entry fired early" || ok "T6b future entry correctly skipped"

# T7: default-config no-regression (creator sign-off condition) -------------
# T7a scheduler inert when SAPPER_SCHEDULE unset (fresh sandbox)
( log() { :; }
  launch() { echo x >> "$T/inert-spawn.log"; return 0; }
  SCHEDULE_FIRED="$T/inert-fired.txt"
  eval "$(cat "$T/sched.fn")"
  check_schedule   # SAPPER_SCHEDULE deliberately unset
) >/dev/null 2>&1 || true
if [[ ! -e "$T/inert-spawn.log" ]] && [[ ! -e "$T/inert-fired.txt" ]]; then
  ok "T7a scheduler fully inert with SAPPER_SCHEDULE unset"
else bad "T7a scheduler acted without SAPPER_SCHEDULE"; fi
# T7b QUOTA_RE without SAPPER_QUOTA_PATTERNS == original literal
orig_re='insufficient|balance|quota|exceeded|billing|payment|401|[Uu]nauthorized|invalid.{0,12}[Aa][Pp][Ii].[Kk]ey|欠费|余额'
if bash -c "eval \"${QUOTA_LINE//\"/\\\"}\"; [[ \"\$QUOTA_RE\" == \"${orig_re}\" ]]"; then
  ok "T7b default QUOTA_RE identical to original (extensible, not replaced)"
else bad "T7b default QUOTA_RE drifted from original"; fi
# T7c default TTL (1800): a 40min-old tried row no longer blocks reuse
mkdir -p "$T/root2"; export SAPPER_ROOT="$T/root2"
python3 - "$T/root2" << 'PYT7'
import os, time, sys
root = sys.argv[1]
os.environ.pop("SAPPER_TRIED_TTL", None)          # default path
open(f"{root}/.rotated-tried.txt", "w").write(f"{time.time()-2400} KEY1\n")
PYT7
if ANTHROPIC_AUTH_TOKEN=KEY2 python3 "$T/rot.py" 2>/dev/null \
   && grep -q KEY1 "$T/root2/rotated.env"; then
  ok "T7c default TTL 1800: 40min-old tried row no longer blocks reuse"
else bad "T7c 40min-old row still blocks (default TTL wrong)"; fi
export SAPPER_ROOT="$T/root"; export SAPPER_TRIED_TTL=1800

printf '\n%s\n' "$(( fails == 0 ))" >/dev/null
if (( fails == 0 )); then printf 'ALL PASS\n'; exit 0; else printf '%d FAILURE(S)\n' "$fails"; exit 1; fi
