#!/usr/bin/env python3
"""Arena adapter template — fill in the five methods to put sapper on your
own scoring platform.

Contract: see ARENA-ADAPTER.md (same directory). Quick rules:
  - every method returns plain dicts (JSON-serializable), raises ArenaError
    on failure — never returns None for "error"
  - submit() must return the canonical response keys (see _SUBMIT_KEYS)
  - standard library only: no httpx/requests/SDK installs inside the box

Install: save as /opt/sapper/lib/arena.py (or point SAPPER_ARENA at it) with
  a sibling arena.json: {"base_url": "...", "token": "..."}.
Smoke test (offline):   python3 arena-template.py selftest
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ARENA_FILE = "arena.json"
DEFAULT_TIMEOUT = 30
TOKEN_HEADER = "X-Benchmark-Token"   # rename to your platform's auth header

_CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

# keys sapper's worker/CLI layers read out of a submit() response
_SUBMIT_KEYS = ("correct", "awarded", "cumulative_score",
                "correct_flag_count", "total_flag_count", "matched_flag_index")


class ArenaError(Exception):
    """User-facing arena failure (bad config, HTTP error, bad payload)."""

    def __init__(self, message: str, *, code: str | None = None,
                 status: int | None = None, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail or {}


class ArenaClient:
    def __init__(self, base_url: str, token: str, *, timeout: int = DEFAULT_TIMEOUT):
        if not (base_url and token):
            raise ArenaError("arena needs base_url and token")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # -- construction -------------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None) -> "ArenaClient":
        """Load config from arena.json next to this file (or $SAPPER_ARENA)."""
        p = Path(path or os.environ.get("SAPPER_ARENA")
                 or Path(__file__).resolve().parent / ARENA_FILE)
        if not p.is_file():
            raise ArenaError(f"no {ARENA_FILE} at {p} — see ARENA-ADAPTER.md")
        cfg = json.loads(p.read_text(encoding="utf-8"))
        return cls(cfg["base_url"], cfg["token"],
                   timeout=int(cfg.get("timeout", DEFAULT_TIMEOUT)))

    # -- HTTP core (keep or adapt; it already matches the error contract) ---
    def _request(self, method: str, path: str, *, params: dict | None = None,
                 body: dict | None = None) -> object:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {TOKEN_HEADER: self.token, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")[:600]
            code, message, detail = None, raw, {}
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    code = payload.get("code")
                    message = payload.get("message", raw)
                    detail = payload.get("detail") or {}
            except json.JSONDecodeError:
                pass
            raise ArenaError(
                f"arena {method} {path} -> HTTP {exc.code}: {message}",
                code=code, status=exc.code, detail=detail) from exc
        except urllib.error.URLError as exc:
            raise ArenaError(f"arena cannot reach {url}: {exc.reason}") from exc
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ArenaError(f"arena {path} returned non-JSON: {raw[:200]}") from exc

    @staticmethod
    def _code(unique_code: str) -> str:
        if not _CODE_RE.match(unique_code or ""):
            raise ArenaError(f"invalid challenge code {unique_code!r}")
        return unique_code

    # -- the five methods you must implement --------------------------------
    def list_challenges(self) -> list[dict]:
        """All challenges. Required keys per item:
        unique_code, is_completed (bool), total_score (int),
        flag_count (int), correct_flag_count (int);
        optional: difficulty, level, description.
        """
        # TODO: return self._request("GET", "/your/list/path")
        raise ArenaError("adapter not implemented: list_challenges")

    def start_challenge(self, unique_code: str) -> dict:
        """Provision an instance. Response should carry the reachable target
        addresses (any of: container_addr / addresses / target fields).
        Must raise ArenaError with your platform's 'max active' code when the
        concurrency cap is hit (watchdog and the commander react to it)."""
        # TODO: return self._request("POST", "/your/start/path",
        #       params={"unique_code": self._code(unique_code)})
        raise ArenaError("adapter not implemented: start_challenge")

    def submit_flag(self, unique_code: str, flag: str) -> dict:
        """Submit one flag. MUST include the canonical keys
        {correct, awarded, cumulative_score, correct_flag_count,
        total_flag_count, matched_flag_index}. Re-submitting an
        already-accepted flag returns correct=false, awarded=0 — that is
        idempotent-OK, not an error."""
        if not isinstance(flag, str) or not flag.strip():
            raise ArenaError("cannot submit an empty flag")
        # TODO: data = self._request("POST", "/your/submit/path",
        #       body={"unique_code": self._code(unique_code),
        #             "flag": flag.strip()})
        # return {k: data.get(k) for k in _SUBMIT_KEYS} | data
        raise ArenaError("adapter not implemented: submit_flag")

    def get_hint(self, unique_code: str) -> dict:
        """Optional (may raise ArenaError('no hints')). Return e.g.
        {"hint": str, "cost_ratio": float}."""
        # TODO: return self._request("GET", "/your/hint/path",
        #       params={"unique_code": self._code(unique_code)})
        raise ArenaError("adapter not implemented: get_hint")

    def close_challenge(self, unique_code: str) -> dict:
        """Release the instance. Prefer an explicit closed:true ack; raising
        on unknown instance is fine (callers treat 404-ish as already-closed)."""
        # TODO: return self._request("POST", "/your/close/path",
        #       params={"unique_code": self._code(unique_code)})
        raise ArenaError("adapter not implemented: close_challenge")

    # -- status convenience (optional; list_challenges filtered) -------------
    def status(self, unique_code: str) -> dict:
        for ch in self.list_challenges():
            if ch.get("unique_code") == self._code(unique_code):
                return ch
        raise ArenaError(f"no such challenge {unique_code!r}")


def _selftest() -> int:
    """Offline structural checks — run before shipping your adapter."""
    here = Path(__file__).resolve().parent
    cfg = here / ARENA_FILE
    if not cfg.is_file():
        print(f"FAIL: {cfg} missing (base_url/token)")
        return 1
    c = ArenaClient.load(str(cfg))
    missing = [m for m in ("list_challenges", "start_challenge", "submit_flag",
                           "get_hint", "close_challenge")
               if getattr(c, m).__doc__ and "not implemented" in getattr(c, m).__doc__]
    # heuristic: unimplemented methods still raise
    unimpl = []
    for m in ("list_challenges",):
        try:
            getattr(c, m)()
        except ArenaError as exc:
            if "not implemented" in str(exc):
                unimpl.append(m)
        except Exception:
            pass  # a REAL response/error means it's implemented
    if unimpl:
        print(f"FAIL: still template stubs: {unimpl} — fill every TODO")
        return 1
    print("OK: adapter implements the five methods; "
          "next: live smoke (list -> start -> submit dummy -> close)")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
