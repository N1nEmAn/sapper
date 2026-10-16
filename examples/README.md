# sapper — worked examples

## Example 1 — a debugging campaign (fgc classic)

The goal is to find why `python reproduce.py` segfaults.

```bash
# 0. set up a workspace
mkdir -p /tmp/sapper-demo && cd /tmp/sapper-demo
cat > reproduce.py <<'EOF'
import sys
print("loading module X")
# ... imagine this segfaults deep in a C extension
raise SystemExit("segfault would happen here in the real case")
EOF

# 1. create the graph
sapper init --origin "user report: segfault" --goal "find root cause of segfault in reproduce.py"

# 2. see it
sapper status
sapper graph                    # full graph as text

# 3. commander proposes the first intents (DRY RUN first to see the prompt)
sapper dispatch reason --dry-run

# 4. for real — sonnet reads the graph and writes intents into .sapper/
sapper dispatch reason

# 5. work the first proposed intent
sapper pick                       # -> i001
sapper dispatch i001

# 6. verify what it claimed
sapper dispatch verify --intent i001

# 7. loop: reason -> explore -> verify until the commander returns {"complete":...}
sapper dispatch reason

# 8. finish
sapper complete --from f003 --note "C extension double-free, patched in v2.1"

sapper status                     # status: completed
```

## Example 2 — an engagement / CTF challenge (sapper native)

```bash
mkdir -p runs/c01 && cd runs/c01
sapper init --goal "break target c01 and submit the flag"

# optional: wire the platform API (fill endpoints from the official doc)
sapper arena init
export SAPPER_ARENA_TOKEN=...

# recon lands as typed facts
sapper fact "10.0.2.15 alive, ports 22,80,3306" -t "主机存活" -k host -d ip=10.0.2.15 -d os=linux
sapper fact "80/tcp nginx 1.18 + php 7.2" -k service -d host=10.0.2.15 -d port=80 -d product=nginx -d version=1.18
sapper fact "admin:admin123 logs into /admin" -k cred -d username=admin -d password=admin123

# exploit, then the moment you see a flag:
sapper flag "flag{s0me_pr00f}" -c c01 --submit
sapper status
#   kinds:  1 hosts, 1 services, 1 creds, 1 flag(s)
#   flag:   f005 status=submitted challenge=c01 value=flag{s0me_pr00f}

# autonomous run bounded by the match clock
sapper auto --skip-permissions --deadline "2026-10-17T13:00:00"

# a whole board of challenges, round-robin
cd .. && sapper sweep --root runs --minutes-per 20 --deadline "2026-10-17T13:00:00" --skip-permissions
```

## resuming

The graph is on disk. Close the terminal, come back tomorrow:

```bash
cd runs/c01
sapper status      # picks up exactly where you left off
sapper graph       # full history of facts + intents
```
