#!/usr/bin/env python3
"""
kb — a shared, offline knowledge base for sapper agents.

One JSON file per entry, stored under a kb root (default: the `kb/` directory
shipped inside the sapper repo, so the knowledge base travels with the git
clone and works air-gapped on a match CVM; override with SAPPER_KB_ROOT or
--root). Any number of agents / graphs share the same base.

Entry shape (kb/entries/kb001.json):

    {
      "id": "kb001",
      "title": "SQL 注入 — 手工确认与绕过",
      "description": "one-line what this entry teaches",
      "detail": "markdown body: methodology, payloads, caveats",
      "commands": ["sqlmap -u 'http://t/?id=1' --batch --dbs"],
      "tags": ["sqli", "web"],
      "source": "hacktricks / writeup URL / 经验",
      "created_at": "2026-10-15T…Z"
    }

Search = token-overlap scoring (title weighted x2, plus description + tags),
same zero-dependency approach as `sapper recall`. Stdlib only.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

_KB_ID_RE = re.compile(r"^kb\d{3,}$")
_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
VALID_TAGS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class KBError(Exception):
    """User-facing kb failure."""


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if any("一" <= ch <= "鿿" for ch in tok):
            out.extend(list(tok))
        else:
            out.append(tok)
    return [t for t in out if t]


class KnowledgeBase:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.entries_dir = self.root / "entries"

    # -- resolution --
    @classmethod
    def default_root(cls) -> Path:
        import os
        env = os.environ.get("SAPPER_KB_ROOT")
        if env:
            return Path(env).expanduser()
        # the kb/ shipped next to lib/ in this repo
        return Path(__file__).resolve().parent.parent / "kb"

    # -- io --
    def ensure(self) -> None:
        self.entries_dir.mkdir(parents=True, exist_ok=True)

    def list_entries(self) -> list[dict]:
        if not self.entries_dir.is_dir():
            return []
        out = []
        for p in sorted(self.entries_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                sys.stderr.write(f"sapper: warning: skipping bad kb entry {p.name}: {exc}\n")
                continue
            if isinstance(data, dict) and isinstance(data.get("id"), str):
                out.append(data)
        return out

    def _next_id(self) -> str:
        n = len(self.list_entries()) + 1
        while (self.entries_dir / f"kb{n:03d}.json").exists():
            n += 1
        return f"kb{n:03d}"

    def add(self, title: str, description: str = "", detail: str = "",
            commands: list[str] | None = None, tags: list[str] | None = None,
            source: str = "", entry_id: str | None = None) -> dict:
        title = (title or "").strip()
        if not title:
            raise KBError("kb entry needs a title")
        tags = [t.strip().lower() for t in (tags or []) if t and t.strip()]
        for t in tags:
            if not VALID_TAGS_RE.match(t):
                raise KBError(f"kb tag {t!r} must match [a-z0-9][a-z0-9_-]*")
        commands = [c.strip() for c in (commands or []) if c and c.strip()]
        if entry_id is None:
            self.ensure()
            entry_id = self._next_id()
        elif not _KB_ID_RE.match(entry_id):
            raise KBError(f"kb entry id must look like kb001, got {entry_id!r}")
        entry = {
            "id": entry_id,
            "title": title,
            "description": (description or "").strip(),
            "detail": (detail or "").strip() or None,
            "commands": commands,
            "tags": tags,
            "source": (source or "").strip() or None,
            "created_at": _now_iso(),
        }
        self.ensure()
        path = self.entries_dir / f"{entry_id}.json"
        if path.exists():
            raise KBError(f"kb entry {entry_id} already exists ({path})")
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return entry

    def get(self, entry_id: str) -> dict:
        if not _KB_ID_RE.match(entry_id):
            raise KBError(f"kb entry id must look like kb001, got {entry_id!r}")
        path = self.entries_dir / f"{entry_id}.json"
        if not path.exists():
            raise KBError(f"kb entry {entry_id} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    # -- search --
    def search(self, query: str, tag: str | None = None, limit: int = 5) -> list[dict]:
        if not query or not query.strip():
            return []
        q_tokens = set(_tokenize(query))
        if not q_tokens:
            return []
        tag = tag.strip().lower() if tag else None
        scored = []
        for e in self.list_entries():
            if tag and tag not in [t.lower() for t in e.get("tags", [])]:
                continue
            title = (e.get("title") or "").lower()
            desc = (e.get("description") or "").lower()
            tags = " ".join(e.get("tags", [])).lower()
            detail = (e.get("detail") or "").lower()
            h_tokens = set(_tokenize(f"{title} {title} {desc} {tags} {detail[:500]}"))
            if not h_tokens:
                continue
            overlap = len(q_tokens & h_tokens)
            if overlap == 0:
                continue
            score = overlap / max(1, len(q_tokens))
            scored.append({**_brief(e), "score": round(score, 3)})
        scored.sort(key=lambda x: (-x["score"], x["id"]))
        return scored[:limit]


def _brief(e: dict) -> dict:
    return {
        "id": e.get("id"),
        "title": e.get("title"),
        "description": e.get("description", ""),
        "tags": e.get("tags", []),
        "has_detail": bool(e.get("detail")),
        "n_commands": len(e.get("commands", [])),
    }


def import_markdown(path: Path, base_tags: list[str] | None = None,
                    source: str = "") -> dict:
    """Import a markdown file as one entry: first '# heading' is the title,
    a ' > ' or italic line right after may serve as description, the rest is
    the detail body."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            title = m.group(1).strip()
            body_start = i + 1
            break
    if not title:
        title = path.stem.replace("-", " ").replace("_", " ")
    body = "\n".join(lines[body_start:]).strip()
    description = ""
    for line in lines[body_start:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith(">"):
            description = s.lstrip("> ").strip()
        break
    return {
        "title": title,
        "description": description,
        "detail": body,
        "tags": list(base_tags or []),
        "source": source or str(path.name),
    }
