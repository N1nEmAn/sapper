#!/usr/bin/env python3
"""
arena — TSecBench (Tencent Cloud) benchmark-platform client for sapper.

Implements the official player-facing Challenges API exactly as documented in
the `tsec-benchmark` SDK (doc/SDK_API.md) and its source:

    base        BENCHMARK_BASE_URL          e.g. https://benchmark.example.com
    auth header BENCHMARK_TOKEN: <token>
    GET  /openapi/v1/challenges                         -> [Challenge, ...]
    POST /openapi/v1/challenges/start?unique_code=CODE  -> StartResult
    GET  /openapi/v1/challenges/hint?unique_code=CODE   -> HintResult
    POST /openapi/v1/challenges/submit {unique_code, flag} -> SubmitResult
    POST /openapi/v1/challenges/close?unique_code=CODE  -> CloseResult

Errors come back as {"code","message","detail"} with an HTTP status; the
common ones (invalid_state "max active", duplicate submit) are surfaced with
their code so the caller can react.

Standard library only (urllib) — no httpx, no SDK install.

Hosted-mode note: the platform injects BENCHMARK_BASE_URL / BENCHMARK_TOKEN
into the container. LLM calls must go through the gateway
(`<host>.tsecbench.gw`, http not https); configure the model CLI with env
vars, not code.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ARENA_FILE = "arena.json"
DEFAULT_TIMEOUT = 30
TOKEN_HEADER = "BENCHMARK_TOKEN"
CHALLENGES_PATH = "/openapi/v1/challenges"

_CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


class ArenaError(Exception):
    """User-facing arena failure (bad config, HTTP error, bad payload)."""

    def __init__(self, message: str, *, code: str | None = None,
                 status: int | None = None, detail: dict | None = None):
        self.code = code
        self.status = status
        self.detail = detail or {}
        super().__init__(message)


class ArenaClient:
    """Synchronous TSecBench Challenges API client (stdlib only)."""

    def __init__(self, base_url: str, token: str, timeout: int = DEFAULT_TIMEOUT):
        if not base_url or not base_url.strip():
            raise ArenaError("arena base_url is empty")
        if not token or not token.strip():
            raise ArenaError("arena token is empty (set BENCHMARK_TOKEN)")
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout

    # -- construction ------------------------------------------------------
    @classmethod
    def config_path(cls, store_root: Path | None = None) -> Path:
        if store_root is not None:
            return Path(store_root) / ARENA_FILE
        return Path(ARENA_FILE)

    @classmethod
    def load(cls, store_root: Path | None = None) -> "ArenaClient":
        """Resolve config: env vars (hosted-mode injection) first, then an
        optional arena.json override in the graph's .sapper/ dir.

        env: BENCHMARK_BASE_URL, BENCHMARK_TOKEN (platform-injected)
        file: {"base_url": ..., "token": "ENV:VAR" | "literal", "timeout": N}
        """
        base_url = os.environ.get("BENCHMARK_BASE_URL") or ""
        token = os.environ.get("BENCHMARK_TOKEN") or ""
        timeout = DEFAULT_TIMEOUT
        cfg: dict = {}
        if store_root is not None:
            path = cls.config_path(store_root)
            if path.exists():
                try:
                    cfg = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    raise ArenaError(f"cannot read arena config {path}: {exc}") from exc
                if not isinstance(cfg, dict):
                    raise ArenaError(f"arena config {path} must be a JSON object")
        if isinstance(cfg.get("base_url"), str) and cfg["base_url"].strip():
            base_url = cfg["base_url"].strip()
        if isinstance(cfg.get("token"), str) and cfg["token"].strip():
            raw = cfg["token"].strip()
            if raw.startswith("ENV:"):
                token = os.environ.get(raw[4:].strip(), "") or token
            else:
                token = raw
        if isinstance(cfg.get("timeout"), int) and cfg["timeout"] > 0:
            timeout = cfg["timeout"]
        if not base_url:
            raise ArenaError(
                "no arena base_url — set BENCHMARK_BASE_URL (the platform injects "
                "it in hosted mode) or write .sapper/arena.json"
            )
        return cls(base_url, token, timeout)

    @classmethod
    def write_template(cls, store_root: Path) -> Path:
        path = cls.config_path(store_root)
        if path.exists():
            raise ArenaError(f"arena config already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "base_url": "https://benchmark.example.com",
            "token": "ENV:BENCHMARK_TOKEN",
            "timeout": 30,
            "_comment": (
                "Hosted mode needs nothing here — the platform injects "
                "BENCHMARK_BASE_URL and BENCHMARK_TOKEN. This file is an "
                "override for local testing / self-hosted runs."
            ),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    # -- transport ---------------------------------------------------------
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
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")[:600]
            code = None
            message = raw
            detail = {}
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
                code=code, status=exc.code, detail=detail,
            ) from exc
        except urllib.error.URLError as exc:
            raise ArenaError(f"arena cannot reach {url}: {exc.reason}") from exc
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ArenaError(f"arena {path} returned non-JSON: {raw[:200]}") from exc

    def _code(self, unique_code: str) -> str:
        if not isinstance(unique_code, str) or not _CODE_RE.match(unique_code):
            raise ArenaError(f"invalid unique_code {unique_code!r}")
        return unique_code

    # -- the five endpoints ------------------------------------------------
    def list_challenges(self) -> list[dict]:
        data = self._request("GET", CHALLENGES_PATH)
        if isinstance(data, dict) and "challenges" in data:
            data = data["challenges"]
        if not isinstance(data, list):
            raise ArenaError(f"challenges endpoint returned {type(data).__name__}, expected list")
        out = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("unique_code"), str):
                out.append(item)
        return out

    def start_challenge(self, unique_code: str) -> dict:
        data = self._request("POST", f"{CHALLENGES_PATH}/start",
                             params={"unique_code": self._code(unique_code)})
        return data if isinstance(data, dict) else {"raw": data}

    def get_hint(self, unique_code: str) -> dict:
        data = self._request("GET", f"{CHALLENGES_PATH}/hint",
                             params={"unique_code": self._code(unique_code)})
        return data if isinstance(data, dict) else {"raw": data}

    def submit_flag(self, unique_code: str, flag: str) -> dict:
        if not isinstance(flag, str) or not flag.strip():
            raise ArenaError("cannot submit an empty flag")
        data = self._request("POST", f"{CHALLENGES_PATH}/submit",
                             body={"unique_code": self._code(unique_code),
                                   "flag": flag.strip()})
        return data if isinstance(data, dict) else {"raw": data}

    def close_challenge(self, unique_code: str) -> dict:
        data = self._request("POST", f"{CHALLENGES_PATH}/close",
                             params={"unique_code": self._code(unique_code)})
        return data if isinstance(data, dict) else {"raw": data}
