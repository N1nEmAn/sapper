# ARENA-ADAPTER.md — putting sapper on a non-TSecBench platform

sapper talks to its scoring platform through exactly one file:
`/opt/sapper/lib/arena.py` (override with the `SAPPER_ARENA` env var). Replace
that file with your own implementation of the five methods below and the
commander / workers / watchdog layers work unchanged. Use
`arena-template.py` (same directory) as the starting point — the HTTP core
and error contract are already wired.

## The five methods

| method | verb+path (yours to choose) | purpose |
|---|---|---|
| `list_challenges()` | GET, collection | catalog + per-challenge progress |
| `start_challenge(code)` | POST | provision an instance, return target addrs |
| `submit_flag(code, flag)` | POST | submit one flag, return the verdict |
| `get_hint(code)` | GET, optional | platform hint (may hard-fail "no hints") |
| `close_challenge(code)` | POST | release the instance |

## Response contracts

**list_challenges** — list of dicts, required keys per item:
`unique_code` (str), `is_completed` (bool), `total_score` (int),
`flag_count` (int), `correct_flag_count` (int). Optional but used when
present: `difficulty`, `level`, `description`.

**start_challenge** — any dict; if it carries `container_addr` /
`addresses` / `target`, sapper passes them straight into the worker mission
text. Errors: raise `ArenaError` with `code=` set to your platform's
"max concurrent instances" code — the commander treats that string as
"slots full", backs off and retries later instead of dropping the challenge.

**submit_flag** — canonical keys, all required:
`correct` (bool), `awarded` (int points for THIS flag),
`cumulative_score` (int points on this challenge so far),
`correct_flag_count`, `total_flag_count` (ints),
`matched_flag_index` (int or null). Re-submitting an already-accepted flag
MUST return `correct:false, awarded:0` — callers rely on this idempotency
and read the verdict from `correct_flag_count`, never from `correct` alone.

**get_hint** — `{"hint": str, "cost_ratio": float}` or raise. A platform
without hints should raise `ArenaError("no hints")`; sapper logs and moves on.

**close_challenge** — `{"closed": true}` ack preferred; raising on an
unknown/expired instance is fine (treated as already closed).

## Error contract (one style for everything)

Raise `ArenaError(message, code=..., status=..., detail=...)`. The HTTP core
in the template already maps your platform's `{"code","message","detail"}`
error bodies onto this, including surfacing the `code` string so callers can
react (e.g. `"duplicate submit"` 409s are understood as idempotent-OK).

## Config & install

1. Copy `arena-template.py` to `/opt/sapper/lib/arena.py` (keep the class
   name `ArenaClient` — `worker.sh`, the watchdog and `sapper arena …` load
   it by that name).
2. Drop `arena.json` next to it: `{"base_url": "https://…", "token": "…"}`
   (plus optional `"timeout"`). Never commit this file — it holds a secret.
3. Rename `TOKEN_HEADER` in the template to your platform's auth header.
4. `python3 arena.py selftest` — structural check, then a live smoke:
   list → start → submit a dummy flag (expect `correct:false`) → close.

## Hard rules

- **Standard library only** inside the box (urllib, not httpx/requests).
- Never widen the interface: exactly these five methods (+ the optional
  `status` convenience). The watchdog greps pane output, not arena calls —
  adapters must not print to stdout on success.
- Scoring units are plain integer points; percentages are the platform UI's
  business, not the adapter's.
