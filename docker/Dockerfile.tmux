# TUI-mode variant: same toolchain as the base image, plus tmux and an
# entrypoint that runs agents as interactive claude sessions in tmux windows
# (driver feeds missions + nudges; sessions stay alive for back-and-forth).
#
# Build:  docker build -f docker/Dockerfile.tmux -t sapper-agent:tmux .
#         (requires sapper-agent:latest to exist locally)
FROM sapper-agent:latest

USER root
RUN apt-get update && apt-get install -y --no-install-recommends tmux \
    && rm -rf /var/lib/apt/lists/*

COPY docker/tmux-drive.sh      /opt/sapper/docker/tmux-drive.sh
COPY docker/entrypoint-tmux.sh /usr/local/bin/sapper-entrypoint
RUN chmod +x /usr/local/bin/sapper-entrypoint /opt/sapper/docker/tmux-drive.sh
USER agent
