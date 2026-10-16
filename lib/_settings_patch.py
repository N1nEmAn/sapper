#!/usr/bin/env python3
"""
_settings_patch — idempotently add/remove fact-graph hooks in ANY Claude Code
settings.json (project-level `<dir>/.claude/settings.json` or user-level
`~/.claude/settings.json`). Called by `sapper enable`/`sapper disable` and by
`install.sh --global-hooks`.

A hook block looks like:

  {
    "hooks": {
      "SessionStart": [
        {"matcher": "", "hooks": [{"type":"command","command":"python3 /abs/sapper-hook.py sessionstart"}]}
      ],
      "UserPromptSubmit": [
        {"matcher": "", "hooks": [{"type":"command","command":"python3 /abs/sapper-hook.py userpromptsubmit"}]}
      ]
    }
  }

Rules:
  - Only adds if our command isn't already present (idempotent).
  - Never removes or alters hooks the user already has.
  - Backs up the file once before the first edit (<path>.bak).
  - On remove, deletes ONLY entries whose command contains MARKER; leaves the
    rest (and the file's other keys) intact.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

MARKER = "sapper-hook.py"

# (hook event name, argv position passed to fg-hook)
HOOK_EVENTS = [
    ("SessionStart", "sessionstart"),
    ("UserPromptSubmit", "userpromptsubmit"),
]


def user_settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "settings.json"


def project_settings_path(project_dir: Path) -> Path:
    return project_dir / ".claude" / "settings.json"


def _cmd(hook_script: str, arg: str) -> str:
    # Use the same interpreter that runs us, and shell-quote the script path so
    # paths with spaces/metachars don't break or inject (review codex#6).
    import shlex
    import sys
    py = shlex.quote(sys.executable or "python3")
    script = shlex.quote(hook_script)
    return f"{py} {script} {arg}"


def _load_settings(settings_path: Path) -> dict:
    if not settings_path.exists():
        return {}
    raw = settings_path.read_text(encoding="utf-8") or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{settings_path} is not valid JSON ({exc.msg} at line {exc.lineno}). "
            f"Fix it by hand before re-running sapper setup."
        )
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{settings_path} is not valid UTF-8 ({exc}). "
            f"Fix it by hand before re-running sapper setup."
        )
    if not isinstance(data, dict):
        raise ValueError(f"{settings_path} must contain a JSON object at the top level")
    return data


def _event_groups(hooks: dict, event: str, *, create: bool) -> list[dict]:
    """Load one event's hook groups while preserving a clear error boundary."""
    if event not in hooks:
        if not create:
            return []
        hooks[event] = []
    groups = hooks[event]
    if not isinstance(groups, list):
        raise ValueError(f"settings hooks.{event} must be a list")
    for idx, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ValueError(f"settings hooks.{event}[{idx}] must be an object")
        hook_list = group.get("hooks", [])
        if not isinstance(hook_list, list):
            raise ValueError(f"settings hooks.{event}[{idx}].hooks must be a list")
        for hidx, hook in enumerate(hook_list):
            if not isinstance(hook, dict):
                raise ValueError(
                    f"settings hooks.{event}[{idx}].hooks[{hidx}] must be an object"
                )
    return groups


def _write_settings(settings_path: Path, data: dict) -> None:
    """Atomically replace settings.json so an interrupted patch cannot leave
    Claude Code with truncated JSON."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{settings_path.name}.", suffix=".tmp", dir=str(settings_path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        if settings_path.exists():
            shutil.copymode(settings_path, tmp)
        os.replace(tmp, settings_path)
    finally:
        tmp.unlink(missing_ok=True)


def validate(settings_path: Path) -> dict:
    """Parse and structurally validate a Claude settings file without editing."""
    data = _load_settings(settings_path)
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings 'hooks' must be an object")
    for event, _arg in HOOK_EVENTS:
        _event_groups(hooks, event, create=False)
    return data


def _has_hook(entries: list, marker: str) -> bool:
    for group in entries:
        for h in group.get("hooks", []):
            if marker in str(h.get("command", "")):
                return True
    return False


def add(settings_path: Path, hook_script: str) -> tuple[bool, list[str]]:
    """Register both hooks into settings_path. Returns (changed, messages)."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_settings(settings_path)
    if settings_path.exists():
        bak = settings_path.with_suffix(settings_path.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(settings_path, bak)

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings 'hooks' must be an object")
    changed = False
    msgs = []
    for event, arg in HOOK_EVENTS:
        groups = _event_groups(hooks, event, create=True)
        if _has_hook(groups, MARKER):
            msgs.append(f"  = {event}: already present")
            continue
        groups.append({
            "matcher": "",
            "hooks": [{"type": "command", "command": _cmd(hook_script, arg)}],
        })
        changed = True
        msgs.append(f"  + {event}: {arg}")

    if changed:
        _write_settings(settings_path, data)
        msgs.append(f"wrote {settings_path}")
    else:
        msgs.append(f"idempotent — nothing changed in {settings_path}")
    return changed, msgs


def remove(settings_path: Path, hook_script: str = "") -> tuple[bool, list[str]]:
    """Remove only our hook entries from settings_path."""
    if not settings_path.exists():
        return False, [f"no {settings_path} — nothing to remove"]
    data = _load_settings(settings_path)
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings 'hooks' must be an object")
    changed = False
    msgs = []
    for event, _arg in HOOK_EVENTS:
        groups = _event_groups(hooks, event, create=False)
        new_groups = []
        removed_here = False
        for group in groups:
            hs = group.get("hooks", [])
            kept = [h for h in hs if MARKER not in str(h.get("command", ""))]
            if len(kept) != len(hs):
                changed = True
                removed_here = True
            if kept:
                group["hooks"] = kept
                new_groups.append(group)
            # else: group had only our hook -> drop it entirely
        hooks[event] = new_groups
        if removed_here:
            msgs.append(f"  - {event}: removed")
    if changed:
        # tidy: drop now-empty hook-event lists and an all-empty hooks block,
        # so we don't leave {\"hooks\":{\"SessionStart\":[],...}} shells behind.
        for event in list(hooks):
            if not hooks[event]:
                del hooks[event]
        if not hooks:
            del data["hooks"]
        _write_settings(settings_path, data)
        msgs.append(f"wrote {settings_path}")
    else:
        msgs.append("no fact-graph hooks found to remove")
    return changed, msgs


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("add", "remove"):
        sys.stderr.write(
            "usage: _settings_patch.py {add|remove} <abs-sapper-hook.py> [settings.json]\n"
            "  (settings.json defaults to the user-level ~/.claude/settings.json)\n"
        )
        return 2
    # `add` requires the hook script path; `remove` can infer it (review codex#10)
    if argv[1] == "add" and len(argv) < 3:
        sys.stderr.write("usage: _settings_patch.py add <abs-sapper-hook.py> [settings.json]\n")
        return 2
    if len(argv) >= 3:
        hook_script = str(Path(argv[2]).resolve())
    else:
        hook_script = ""
    if len(argv) >= 4:
        target = Path(argv[3])
    else:
        target = user_settings_path()
    fn = add if argv[1] == "add" else remove
    try:
        _, msgs = fn(target, hook_script)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"_settings_patch: {exc}\n")
        return 1
    for m in msgs:
        print(m)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
