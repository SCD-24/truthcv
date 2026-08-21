# Unattended job-application agent — its own container (see docker-compose.yml
# `agent` service and task t-2 of plan agent-container-and-schedule), separate
# from `app` so a browser crash can never take the wizard down.
#
# BROWSER STRATEGY — DELIBERATE DIVERGENCE FROM THE RETIRED "Jobs" CONTAINER
# ----------------------------------------------------------------------------
# The retired Jobs project's docker/Dockerfile ran a containerised, freshly
# provisioned Google Chrome under Xvfb. THIS IMAGE DOES NOT INSTALL CHROME,
# CHROMIUM, XVFB, OR ANY OTHER BROWSER — do not "fix" that by adding one back.
#
# TruthCV's agent instead drives the operator's real, already-logged-in browser on
# the HOST. The `claude` CLI spawns `interceptor mcp serve` over stdio in-container
# (see agent/mcp.json), and that subprocess shells to the real `interceptor <verb>`
# command (a Bun-compiled binary bind-mounted read-only at /opt/interceptor/bin/interceptor,
# see docker-compose.yml's volumes). The binary dials the host interceptor daemon
# over a unix socket bind-mounted into the container at INTERCEPTOR_SOCKET (also in
# docker-compose.yml), and the daemon reaches Chrome via native messaging on the host.
# A container's own browser starts from a blank profile with no logins, and unattended
# applying depends entirely on sessions that already exist in the operator's real browser
# (ATS accounts, SSO, etc.) — a fresh containerised Chrome cannot reproduce that, so it
# cannot do this job at all, it can only look like it can.

FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    NODE_ENV=production

# ca-certificates: TLS for the claude CLI and for this container's calls to
# ${TRUTHCV_MCP_URL}. tzdata: RUN_AT (docker-compose.yml) is a container-TZ
# schedule, same as the retired Jobs project's RUN_AT.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

# The claude CLI — install command carried over unchanged from the Jobs
# project's docker/Dockerfile. @playwright/mcp is deliberately NOT installed
# here: see the BROWSER STRATEGY note above and agent/mcp.json.
RUN npm install -g @anthropic-ai/claude-code

# node:22-bookworm-slim already ships a `node` user at UID 1000 — reuse it
# rather than create a second UID-1000 account, which fails (same reasoning
# as the Jobs project's docker/Dockerfile).
# /app/runs is created HERE, owned by node, so the named volume that
# docker-compose.yml mounts over it inherits that ownership — a volume mounted
# onto a path the image does not contain is created root-owned, and the agent
# (USER node) could then not write its run logs.
# /opt/interceptor/bin is the mount target for the host interceptor binary
# (docker-compose.yml volumes), created here so the mount succeeds even if
# the path doesn't exist in the base image.
RUN mkdir -p /app/agent /app/runs /opt/interceptor/bin \
 && chown -R node:node /app

# The agent's own files — its operating spec, its prompt, its MCP config, the
# per-run script and the scheduling loop that invokes it (task t-3 of plan
# agent-container-and-schedule).
COPY --chown=node:node agent/RUNBOOK.md      /app/agent/RUNBOOK.md
COPY --chown=node:node agent/prompt.md       /app/agent/prompt.md
COPY --chown=node:node agent/mcp.json        /app/agent/mcp.json
COPY --chown=node:node agent/daily-apply.sh  /app/agent/daily-apply.sh
COPY --chown=node:node agent/entrypoint.sh   /app/agent/entrypoint.sh
# Fetches enabled/runAt/runDays from the app's agent config API (Agents
# page) — see entrypoint.sh's refresh_schedule() and daily-apply.sh's enable
# gate, both of which invoke this via `node`.
COPY --chown=node:node agent/agent-config.js /app/agent/agent-config.js
# The smoke test is shipped IN the image, not just kept in the repo: it is run
# via `--entrypoint /app/agent/smoke-test.sh` against the built container, and
# its whole point is to test the image as shipped (agent/README.md).
COPY --chown=node:node agent/smoke-test.sh   /app/agent/smoke-test.sh
RUN chmod +x /app/agent/daily-apply.sh /app/agent/entrypoint.sh /app/agent/smoke-test.sh

USER node
WORKDIR /app/agent

ENTRYPOINT ["/app/agent/entrypoint.sh"]
