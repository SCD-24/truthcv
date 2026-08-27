# Unattended job-application agent — its own container (see docker-compose.yml
# `agent` service and task t-2 of plan agent-container-and-schedule), separate
# from `app` so a browser crash can never take the wizard down.
#
# BROWSER STRATEGY — DELIBERATE DIVERGENCE FROM THE RETIRED "Jobs" CONTAINER
# ----------------------------------------------------------------------------
# The retired Jobs project's docker/Dockerfile ran a containerised, freshly
# provisioned Google Chrome under Xvfb inside the SAME image as the agent.
# THIS IMAGE DOES NOT INSTALL CHROME, CHROMIUM, XVFB, OR ANY OTHER BROWSER —
# do not "fix" that by adding one back.
#
# TruthCV does run a real browser, just never inside THIS image. There is a
# single containerised driver, selected per deployment by AGENT_BROWSER_DRIVER
# (docker-compose.yml), and the agent image is browserless under it.
#
# `browser`: a separate compose service (browser/Dockerfile — headful
# Chromium under Xvfb served by @playwright/mcp), driven over in-network HTTP
# MCP at ${BROWSER_MCP_URL} (default http://browser:8931/mcp; see agent/mcp.json's
# `browser` server). Keeping the two apart is the point: a browser crash or a
# runaway Chromium cannot take the scheduled agent loop down with it, and the two
# images can be rebuilt independently.
#
# The old objection to a containerised browser was that a blank profile has no
# logins, and unattended applying depends on live ATS/SSO sessions. That is
# answered by the browser service, not by the host: its Chromium profile lives
# on the persistent `browser-profile` volume, and the operator establishes those
# sessions once by hand through the Agents page → Site sign-ins, which relays
# the noVNC viewport through the app for the duration of that sign-in, after
# which they survive restarts. The viewport is not a way to watch a run: a run
# and a sign-in session cannot both hold the profile, and the run wins.
#
# NOTHING that renders a page is installed below — do not "fix" the absence of
# a browser in this image by adding one back.

FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    NODE_ENV=production

# ca-certificates: TLS for the harness's provider calls and for this
# container's calls to ${TRUTHCV_MCP_URL}. tzdata: RUN_AT (docker-compose.yml)
# is a container-TZ schedule, same as the retired Jobs project's RUN_AT. jq:
# agent/daily-apply.sh renders the entire job-profile / criteria / salary
# prompt block with it, and now aborts the run outright when it is missing
# rather than silently dropping every configured profile.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tzdata jq \
 && rm -rf /var/lib/apt/lists/*

# node:22-bookworm-slim already ships a `node` user at UID 1000 — reuse it
# rather than create a second UID-1000 account, which fails (same reasoning
# as the Jobs project's docker/Dockerfile).
# /app/runs is created HERE, owned by node, so the named volume that
# docker-compose.yml mounts over it inherits that ownership — a volume mounted
# onto a path the image does not contain is created root-owned, and the agent
# (USER node) could then not write its run logs.
RUN mkdir -p /app/agent /app/runs \
 && chown -R node:node /app

WORKDIR /app/agent

# Build the harness (agent/harness/) as our own dependency, pinned exactly by
# the lockfile — the same reproducibility rationale that once applied to the
# earlier CLI-based agent (historical, no longer used here): a rebuild today
# vs. next month must not silently change behavior out from under an unattended
# run. Copy the manifest + lockfile first so this layer only rebuilds when
# dependencies actually change.
COPY --chown=node:node agent/package.json agent/package-lock.json ./
RUN npm ci --include=dev
COPY --chown=node:node agent/tsconfig.json ./
COPY --chown=node:node agent/harness ./harness
RUN npm run build && npm prune --omit=dev

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
# The scheduling loop and control-server HTTP surface. entrypoint.sh execs
# this as its final step, so the image does not start without it.
COPY --chown=node:node agent/supervisor.js   /app/agent/supervisor.js
# The smoke test is shipped IN the image, not just kept in the repo: it is run
# via `--entrypoint /app/agent/smoke-test.sh` against the built container, and
# its whole point is to test the image as shipped (agent/README.md).
COPY --chown=node:node agent/smoke-test.sh   /app/agent/smoke-test.sh
RUN chmod +x /app/agent/daily-apply.sh /app/agent/entrypoint.sh /app/agent/smoke-test.sh

USER node

ENTRYPOINT ["/app/agent/entrypoint.sh"]
