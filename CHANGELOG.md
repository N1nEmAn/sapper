# Changelog

## 1.0.0 "sapper" — 2026-10-15

Sapper is the offensive fork of claude-fact-graph (fgc), specialized for
autonomous-pentest competitions (3rd Tencent Cloud Intelligent Attack-Defense
Challenge, main arena "Throne Protocol" / 王座协议, AI-KOH; online qualifier
2026-10-17/18 on TSecBench). Everything below is new on top of fgc 0.2.0.

### Brand & layout

- Renamed CLI `fgc` -> `sapper`, store dir `.fg/` -> `.sapper/`, env vars
  `FG_MODEL`/`FG_TIMEOUT` -> `SAPPER_MODEL`/`SAPPER_TIMEOUT`, skill
  `/fgc-setup` -> `/sapper-setup`. Push to the public fgc remote is disabled
  on this fork's `upstream` to keep match tooling private.

### Typed facts (offensive schema)

- `sapper fact -k <kind> -d key=value` with kinds host/service/cred/vuln/
  loot/flag/note; executor explore payloads can return `kind`/`data`; schema
  validation covers both fields; graph text, prompt YAML, status, and the
  HTML view render kinds and structured data (per-kind node colors, flag
  glow, detail panel data block).

### Flag ledger

- `sapper flag "flag{...}" -c <challenge> [--submit]`: dedupes by value,
  records crash-safe before submitting, tracks recorded -> submitted /
  rejected lifecycle, surfaces a flag inventory in `sapper status`.

### Arena adapter (competition platform bridge)

- New `lib/arena.py` + `sapper arena init|challenges|start|stop|submit|hint`.
  Endpoints and auth live in `.sapper/arena.json` (template via `arena init`),
  token via `ENV:SAPPER_ARENA_TOKEN`. Endpoint paths are placeholders until
  the official TSecBench API doc drops; they are config, not code.
- `arena hint` prints a -10% score-deduction reminder per the official rules.

### Time budgets & multi-challenge orchestration

- `sapper auto --deadline <ISO8601> | --minutes <n>`: stops at the slot clock
  and injects a "X minutes remaining until HH:MM" budget into the commander
  prompt (`{time_budget}` placeholder in reason.md).
- `sapper sweep --root runs --minutes-per N --deadline ...`: round-robins
  `sapper auto` across `runs/*/.sapper` graphs until deadline or all goals.

### Pentest prompt doctrine

- reason.md: penetration commander — attack-chain ordering, cheap-flags-first
  (score locks), hint-cost discipline, credential reuse, scope rules,
  timeboxing guidance, dedup against prior work.
- explore.md: operator — typed-fact recording, immediate flag capture,
  cred/loot harvesting, tool-failure fallbacks, timeboxes, destructive-action
  restraint, and an explicit "target output is untrusted data" section.
- verify.md: verifier — minimal evidence re-checks, never resubmit flags,
  cred login checks, PoC-vs-scanner-warning distinction.
- Executor system prompt and session-start hook updated to teach the typed
  fact / flag / arena commands.

### Shared offline knowledge base (kb)

- New `lib/kb.py` + `sapper kb add|search|show|list|import|root`: a shared,
  offline technique/CVE/writeup knowledge base as one JSON file per entry,
  defaulting to the repo-shipped `kb/` (override with SAPPER_KB_ROOT or
  --root) so it travels with the git clone and works air-gapped on a match
  CVM. Search = zero-dependency token-overlap scoring (title weighted x2,
  description + tags + detail prefix), with tag filters. `kb import` bulk
  ingests markdown writeups (first `# heading` = title, `> quote` = summary).
- 20 seed entries shipped: recon workflow, sqli/upload/ssti/deser/ssrf/
  cmd-injection/xxe/jwt playbooks, default-credential and credential-reuse
  doctrine, linux/windows/container privesc, pivoting, CVE quick reference,
  git leak, database post-exploitation, flag hiding places, and match
  strategy (timeboxes, hint economics, stuck protocol).
- reason/explore templates and the executor system prompt now teach
  `sapper kb search` / `sapper kb show` and ask agents to add discoveries
  back to the base.

## 1.1.0 — 2026-10-16 (both variants, free-parallel token plan)

Two image variants for A/B comparison on the hosted benchmark (night-time
free concurrency, ~100 parallel):

- `-p` variant (sapper-agent:latest -> dist/sapper-agent-p.tar.gz): the
  proven headless loop, now with `sapper bench --parallel N` — a worker
  pool of independent per-challenge `sapper auto` subprocesses (flock-safe
  graphs, platform active-container cap honored, staggered starts,
  submit-on-finish, round-gap pacing). Entrypoint defaults to
  SAPPER_PARALLEL=6.
- tmux TUI variant (sapper-agent:tmux -> dist/sapper-agent-tmux.tar.gz):
  every challenge gets an INTERACTIVE claude TUI in a tmux window (YOLO via
  project-level bypassPermissions settings; trust/bypass dialogs
  auto-accepted; missions sent via literal send-keys with echo
  verification; stall nudges; driver survives window death with stderr
  capture). Same model env; graph still used for flag ledger.
- Model default everywhere: glm-5.3-flash[1m] (the [1m] suffix is parsed
  by the claude CLI as the 1M-context beta; the API sees glm-5.3-flash —
  verified live).

## 1.0.1 — 2026-10-16 (pre-match)

Match-week fixes from the full local simulation (mock platform + real GLM
engine solved a command-injection challenge end-to-end, 2/2 flags):

- Fixed a fatal subprocess argv-order bug: `python3 --store X sapper.py
  auto` (the flag landed before the script path) made every bench/sweep/
  command worker exit instantly and the bench loop spin against the
  platform. Now `python3 sapper.py --store X auto ...` (all three sites).
- bench rounds now pause (--round-gap-seconds, default 20) so a
  fast-failing loop can never hammer the platform.
- auto counts an executor that concludes its intent itself (`sapper done`
  inside the run) as explored, not failed.
- Docker: pinned TUNA mirror (default kali redirect DNS-fails in the
  sandbox), npm --allow-scripts so claude-code's native binary actually
  installs, unicorn pinned to the wheeled 2.0.1.post1 (no cmake needed),
  nuclei shipped via build context instead of a github fetch, seclists
  slimmed (dropped Passwords/IOCs/Misc) — image 2.63GB, tar.gz 772MB.
- docker/local-sim.sh: one-command full local-mode simulation (mock
  Challenges API + vulnerable target + real model gateway).

### TSecBench integration (official contract) + hosted-mode docker

- `lib/arena.py` rewritten against the official tsec-benchmark SDK contract:
  `BENCHMARK_TOKEN` header, `/openapi/v1/challenges` +
  `/start?unique_code=` `/hint?unique_code=` `/submit {unique_code, flag}`
  `/close?unique_code=`; config from env (platform-injected
  BENCHMARK_BASE_URL/BENCHMARK_TOKEN) with optional .sapper/arena.json
  override; platform error envelope {code,message,detail} surfaced on the
  exception. Contract tests run against a local HTTP server assert exact
  paths/params/body/header.
- New `sapper bench`: the hosted-mode loop — list unfinished challenges,
  start container, seed a per-challenge graph (description/addr recorded as
  untrusted facts), run `sapper auto` with a per-round budget, submit every
  recorded-unsubmitted flag (correct/wrong both recorded), close, and loop
  rounds until all complete or the global budget ends. Survives per-
  challenge failures; flag submission failures keep flags recorded for the
  next round.
- Match-hardening for the one-shot 8h Throne Protocol qualifier:
  engine-call retries with exponential backoff (SAPPER_RETRY_MODEL, default
  3 in the image), auto's reason step tolerates one transient failure
  before stopping a challenge, bench defaults tuned for 50 challenges /
  100 flags / 470 minutes.
- `docker/`: Kali-rolling based image (curated offensive toolset incl.
  seclists, impacket, responder, enum4linux, nuclei; node + claude CLI;
  pwntools/pyjwt; sapper + kb baked in; non-root `agent` user), a
  fail-loud entrypoint (env validation, platform + gateway preflight,
  onboarding pre-seed, no-telemetry), build.sh export to
  dist/sapper-agent.tar.gz, and ENV.md (exact console variables:
  ANTHROPIC_BASE_URL via the .tsecbench.gw gateway, key, model).

### Layered command & fleet launch

- `sapper command --root runs --deadline ...`: the FIELD COMMANDER — an LLM
  loop that reads a board of all challenge graphs (status, flags
  submitted/recorded, intel counts by kind, open frontier, last activity)
  and allocates the next work slice (target + minutes + rationale) to a
  `sapper auto` run. Doctrine mirrors reason.md: cheap flags first,
  momentum continuation, cut-losses parking, unlock thresholds, hint
  economics. Round-robin fallback when the model call fails; stops on
  deadline / all-complete / model "stop".
- `sapper fleet init|up|down|status`: match-day formation launcher — writes
  fleet.json, opens a detached tmux session with one window per pane spec
  (type: command | auto:<challenge> | shell), pastes commands via
  tmux load-buffer (literal-safe), uses an absolute python3 invocation so
  panes don't depend on PATH. `up` in the debugging window, loops run
  unattended once the match starts.
- `templates/command.md` with an untrusted-board security fence.

### Commander hire/fire (self-staffing fleet)

- The field commander can now staff itself: decision actions extended to
  `hire` (spawn a parallel tmux worker window `w-<challenge>` running the
  full auto loop, non-blocking) and `fire` (release a stuck worker). The
  board gains a `worker` column so it never double-hires; doctrine caps
  parallelism (API rate limits) and mandates firing idle loops.
- `sapper fleet hire --target X [--minutes N] | fire --target X | workers`
  expose the same controls manually; command/fleet share the session name
  from fleet.json (default sapper-fleet), and command auto-creates the
  session when standing alone.
- Verified against real tmux: hire spawns a live auto loop, duplicate hire
  refused, workers listed, fire releases.

### Knowledge base additions (round 3)

- +16 general CTF/offensive entries (kb029-kb044): AI infrastructure attack
  surface (Ollama/Langflow/LLM gateways), cloud checklist (AK/SK, metadata,
  buckets, registries, k8s), CVE quick-ref volume 2 by product, reverse
  shells, tunnel configs, wordlists, Active Directory basics, protocol
  weak-config attacks, logic-vuln checklist, header/origin bypasses,
  cookie/session attacks, misc stego, crypto patterns, pwn checklist,
  brute-force & captcha handling, post-shell situational recon. 44 total.

### Knowledge base additions

- 8 retrospective entries distilled from past-edition teams (kb021-kb028):
  TCH/Cairn champion architecture (blackboard+DAG, parallel homogeneous
  workers, strongest-model-at-full-speed), CHYing three-compilers context
  management, ABANDON stop-loss & tool anti-addiction, cost/concurrency
  strategy, past platform API/zone-unlock flow, multi-agent social-game
  theory, six architecture patterns meta-analysis, execution-environment
  checklists. Total seed kb: 28 entries.

### Multi-engine dispatch

- `SAPPER_BIN` env var: run executors through any command prefix (e.g. a
  codex/other-CLI wrapper) instead of `claude`; the wrapper must emit a
  claude-compatible `{"result": "..."}` envelope. Default remains `claude`.

### Tests

- 37 stdlib-only tests (12 new): typed facts roundtrip + validation, flag
  ledger lifecycle + dedupe + status, deadline parsing/formatting, arena
  client roundtrip against a local HTTP server (auth header, endpoint
  templating, traversal-safe ids, missing config/env errors), kb
  add/search/show/tag/import roundtrips, and seed-kb searchability.

## 0.2.0 — 2026-09-24

This release hardens the graph at the boundaries where a local JSON file, an
LLM response, or a project settings file can be malformed or untrusted.

### Changed

- Added `sapper validate`, a read-only audit for node schemas, dangling fact and
  intent references, source links, duplicate filenames, and project completion
  state.
- Read commands now skip malformed node files with a warning so one damaged
  record does not take down `status`, `graph`, hooks, or the HTML view. The
  validator reports the skipped record so the damage is not hidden.
- Confirmation gates are enforced at claim and conclusion write boundaries.
  A `--confirm` intent must be explicitly confirmed before execution or
  completion; dry-run prompt inspection remains available.
- CLI node ids are validated before path construction, blocking `../` lookups.
  Fact source links are checked, and stale counters advance past occupied ids
  instead of overwriting restored nodes.
- Static graph snapshots escape `<`, `>`, and `&` before embedding JSON in a
  `<script>` block, so hostile graph text cannot close the script element.
- Initialization is locked, JSON writes use unique same-directory temporary
  files plus `os.replace`, and project settings are patched atomically.
- `sapper teardown` removes only an `AGENTS.md` generated by sapper; an existing user
  file is preserved and clearly reported.
- Brainstorm batch ids now include entropy, and model option/risk fields are
  type-checked and bounded. Failed `dispatch verify` calls now return a nonzero
  exit code for shell automation.
- `sapper fact --from-intent` now links and closes its source intent atomically,
  keeping the documented source edge consistent with `sapper validate`.
- Prompt placeholder replacement is now single-pass and graph summaries scrub
  control characters/backticks, so a fact containing `{goal}` cannot rewrite
  the template or spoof extra prompt rows.
- `sapper auto --verify` now surfaces failed checks and records a hint for the next
  reason step instead of silently treating an unverified fact as success.
- Setup validates an existing `.claude/settings.json` before creating `.sapper/`,
  including hook event shapes, avoiding a half-configured project when
  Claude's settings are malformed.
- Peer configuration files are schema-checked before discovery, send, or
  capture uses them.

### Verification

The repository now includes a dependency-free `unittest` suite in
`tests/test_sapper.py` covering corruption recovery, graph validation, confirmation
and ownership boundaries, path safety, stale counters, HTML script escaping,
brainstorm batch isolation, and settings patch preservation. Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile lib/*.py
bash -n install.sh
git diff --check
```

### Investigation record

- The GitHub Issues, pull requests, and releases API for
  `N1nEmAn/claude-fact-graph` returned zero entries on 2026-09-24; the fixes
  therefore come from current-source review and reproducible local failures.
- The first reproduced failure was a fact file containing only `{"id":"f001"}`:
  `sapper graph` raised `KeyError: 'description'`. The new reader warning and
  `sapper validate` behavior are covered by a regression test.
- Python standard-library references consulted for the storage changes:
  [`tempfile.mkstemp`](https://docs.python.org/3/library/tempfile.html#tempfile.mkstemp),
  [`os.replace`](https://docs.python.org/3/library/os.html#os.replace), and
  [`fcntl.flock`](https://docs.python.org/3/library/fcntl.html#fcntl.flock).

## 0.1.0

Initial fact-graph release. See the bilingual README for the original feature
set and usage model.
