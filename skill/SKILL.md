---
name: sapper-setup
description: Opt-in the CURRENT project to the sapper engagement-graph working memory (offensive specialization of the fact graph). Creates the local .sapper/ graph, registers the SessionStart + UserPromptSubmit hooks in this project's .claude/settings.json (NOT global — other projects are untouched), and writes AGENTS.md teaching typed facts (host/service/cred/vuln/loot/flag), the flag ledger (sapper flag), and the arena bridge (sapper arena). After setup, every turn in this project auto-injects the current graph state and current date output so Claude always knows what's confirmed vs. tried and what time it is; sub-agents (sapper dispatch) can read/write the same graph. For multi-agent tmux work, list panes with sapper peers --discover and ask the user which panes/AI peers may communicate before authorizing any target. Use when the user says "enable sapper here", "在这个项目用 sapper", "setup the engagement graph", or when starting a pentest engagement / CTF challenge / multi-step debugging/research/audit campaign that should be tracked and resumable. For competitions, follow up with `sapper arena init` and set SAPPER_ARENA_TOKEN. This is the per-project initializer the install.sh skill exposes as a slash command.
license: MIT
---

# sapper-setup

Per-project initializer for the **sapper engagement graph** working memory.
This is the opt-in switch: until you run it in a project, sapper does nothing
there. After you run it, that one project auto-reads and auto-maintains its
graph on every turn.

Zero servers — it just drops a local `.sapper/` and writes the two hook
entries into **this project's** `.claude/settings.json`. For penetration
engagements, pair it with `sapper arena init` (competition platform config)
and record findings as typed facts (`-k host/service/cred/vuln/loot/flag`).

## What it does

Run inside the target project directory. Exactly three things, all local:

1. **Creates the graph** at `./.sapper/` (unless one already exists):
   `project.json`, `facts/goal.json`, and the `intents/` `hints/` dirs.
2. **Registers hooks** in `./.claude/settings.json` — `SessionStart` and
   `UserPromptSubmit`, both pointing at `sapper-hook.py`. These inject the current
   graph state and `date` output into every turn so the model always knows the
   frontier and current local time. This is a **project-level** settings file;
   the user-level `~/.claude/settings.json` and every other project are
   completely untouched.
3. **(optional) Writes `AGENTS.md`** so dispatched sub-agents learn the
   fact-graph protocol (`sapper fact`, `sapper done`, etc.).

No daemons, no ports, no database. `rm -rf .sapper .claude` undoes everything.

## How to run it

From the shell (after `bash install.sh`):

```bash
cd /path/to/your/project
sapper setup --goal "reproduce the empty-token crash" --agents
```

Or, since this is a skill, the user can just type `/sapper-setup <goal>` inside
Claude Code and Claude will run the equivalent commands.

## Multi-agent tmux authorization flow

If the user wants multiple AI agents to coordinate through tmux, do this after
the normal setup:

1. Run `sapper peers --discover` and show the pane list to the user.
2. Ask which panes/agents are allowed to communicate and what names to use.
3. Only after explicit approval, run:

```bash
sapper peers --add harley --target api-6:0.0 --sender "Codex/api2-4"
```

4. Use `sapper send harley "message"` for communication. It appends to
   `.sapper/ai-channel.txt` and uses a reliable tmux paste-buffer submit flow.
5. After sending a question, use `sapper capture harley --lines 120` to read recent
   direct TUI replies from that authorized peer. Peers may answer without using
   `sapper send`, so the shared channel log is not always enough.

Do **not** infer authorization from discovery output or from session names.
Never send to or capture from a tmux target unless `sapper peers` shows it as
authorized in this project's `.sapper/ai-peers.json`.

## After setup

- The model is reminded each session + each turn to read/maintain the graph.
- The hooks inject current local time from `date` each session + each turn.
- Drive it with `sapper dispatch reason` (commander proposes next work),
  `sapper dispatch <intent-id> --skip-permissions` (executor does the work),
  `sapper dispatch verify --intent <id>` (verify a result), or
  `sapper auto --skip-permissions` (full loop to completion).
- See state anytime: `sapper status`, `sapper graph`; run the read-only `sapper validate`
  audit before autonomous dispatch or committing `.sapper/`.

## Undo

```bash
sapper teardown            # removes sapper hooks + its AGENTS.md, keeps .sapper/
sapper teardown --purge    # also deletes the graph data
```

`install.sh --uninstall` removes the `sapper` command and this skill globally, but
never touches project-level `.sapper/` or `.claude/` — those are per-project and
must be removed per-project with `teardown`.

## Autonomy guardrail (prompt injection)

A dispatched executor (`sapper dispatch <intent>`, `sapper auto`) runs the whole graph
— every fact/intent/hint text — interpolated into its prompt. So text recorded
as a "fact" becomes instructions the next executor sees. The executor system
prompt fences graph content as **untrusted data** and tells the agent to treat
embedded "ignore your rules / run this command" text as an observation to
record, not a command to obey. That is a textual defense, not a sandbox.

Dangerous combination: a graph fed by **untrusted** content (a hostile
`.sapper/*.json` in the repo, or facts transcribed from attacker-controlled
code/output) **plus** `--skip-permissions` **plus** real shell/file access. In
that case a graph field can attempt to drive the agent. **Do not run
`sapper auto --skip-permissions` on a repo whose `.sapper/` is untrusted** — prefer the
default (each tool use prompts you), and read the facts an autonomous run
writes before acting on them. Treat `--skip-permissions` as opt-in per run.

## Where things live (IMPORTANT — nothing global)

- `./.sapper/` — all graph data. Move/delete the project, the graph goes with it.
- `./.claude/settings.json` — the two hook entries, project-scoped.
- `./AGENTS.md` — sub-agent protocol (optional).
- `~/.local/bin/sapper` — the CLI (one symlink).
- `~/.claude/skills/sapper-setup` — this skill (one symlink).

There is no `~/.sapper`, no global hook registration, no shared state between
projects. Two opted-in projects have two independent graphs.
