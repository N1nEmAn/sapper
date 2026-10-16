#!/usr/bin/env bash
# install.sh — install the `sapper` CLI + the `sapper-setup` project skill.
#
# This installer does NOT touch ~/.claude/settings.json and does NOT register
# any global hooks. The fact-graph is strictly per-project opt-in: you opt a
# project in by running `sapper setup` (or the /sapper-setup skill) inside that
# project, which writes ./.claude/settings.json + .sapper/ there.
#
# Usage:
#   bash install.sh              # install CLI + project skill (recommended)
#   bash install.sh --cli-only   # just symlink sapper, skip the skill
#   bash install.sh --uninstall  # remove the symlink + the skill
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/lib/sapper.py"
mode="${1:-install}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "install: python3 is required (stdlib only, no pip)." >&2
  exit 1
fi

# --- uninstall -------------------------------------------------------------
if [[ "$mode" == "--uninstall" ]]; then
  rm -f "${HOME}/.local/bin/sapper"
  echo "removed ~/.local/bin/sapper"
  if [[ -e "${HOME}/.claude/skills/sapper-setup" || -L "${HOME}/.claude/skills/sapper-setup" ]]; then
    rm -f "${HOME}/.claude/skills/sapper-setup"
    echo "removed ~/.claude/skills/sapper-setup"
  fi
  echo "uninstalled."
  echo "(Project-level .sapper/ graphs and ./.claude/settings.json in your projects are untouched."
  echo " Remove them per-project with: cd <project> && sapper teardown --purge)"
  exit 0
fi

# --- install CLI -----------------------------------------------------------
if [[ ! -f "$SRC" ]]; then
  echo "install: sapper.py not found at $SRC" >&2; exit 1
fi

DEST_DIR="${HOME}/.local/bin"
mkdir -p "$DEST_DIR"
if [[ -e "$DEST_DIR/sapper" || -L "$DEST_DIR/sapper" ]]; then
  rm -f "$DEST_DIR/sapper"
fi
ln -s "$SRC" "$DEST_DIR/sapper"
chmod +x "$SRC"
echo "installed: sapper -> $DEST_DIR/sapper"

case ":$PATH:" in
  *":$DEST_DIR:"*) ;;
  *) echo "install: NOTE — $DEST_DIR is not on your PATH. Add:" >&2
     echo "    export PATH=\"$DEST_DIR:\$PATH\"" >&2 ;;
esac

"$DEST_DIR/sapper" --version >/dev/null && echo "  (sapper works)"

if [[ "$mode" == "--cli-only" ]]; then
  echo "(--cli-only: skipping the /sapper-setup skill)"
  exit 0
fi

# --- install the project skill --------------------------------------------
SKILLS_DIR="${HOME}/.claude/skills"
mkdir -p "$SKILLS_DIR"
SKILL_LINK="$SKILLS_DIR/sapper-setup"
if [[ -e "$SKILL_LINK" || -L "$SKILL_LINK" ]]; then
  rm -f "$SKILL_LINK"
fi
ln -s "${SCRIPT_DIR}/skill" "$SKILL_LINK"
echo "installed: /sapper-setup skill -> $SKILL_LINK"

cat <<'NOTE'

Done. Nothing global was configured — the fact-graph is per-project opt-in.

To opt a project IN (run inside the project dir):
  sapper setup --goal "your one-line goal" --agents
  #  ↑ creates ./.sapper/  +  registers hooks in ./.claude/settings.json  +  AGENTS.md

Or just invoke the skill from inside Claude Code:
  /sapper-setup <your goal>

After that, every turn in that project auto-injects the current graph state,
and you can drive it with `sapper dispatch reason` / `sapper auto`.

To opt a project OUT:
  cd <project> && sapper teardown           # removes hooks + AGENTS.md (keeps .sapper/)
  cd <project> && sapper teardown --purge   # also deletes the graph data
NOTE
