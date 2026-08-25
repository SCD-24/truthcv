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
# TruthCV does run a real browser, just never inside THIS image. There are two
# drivers, selected per deployment by AGENT_BROWSER_DRIVER (docker-compose.yml),
# and the agent image is browserless under both.
#
# DEFAULT — `browser`: a separate compose service (browser/Dockerfile — headful
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
# sessions once by hand through the noVNC viewport at http://localhost:5628,
# after which they survive restarts.
#
# OPT-IN — `interceptor`: the operator's real, already-logged-in Chrome on the
# HOST. The `claude` CLI spawns `interceptor mcp serve` over stdio in-container
# (agent/mcp.json's `interceptor` server); that subprocess shells to the real
# `interceptor <verb>` command — a Bun-compiled binary bind-mounted read-only at
# /opt/interceptor/bin/interceptor — which dials the host daemon over a
# bind-mounted unix socket, and the daemon reaches Chrome via native messaging.
# Both bind mounts come from docker-compose.interceptor.yml, an overlay the
# operator opts into, NOT from docker-compose.yml: their sources exist only on a
# host actually running Interceptor, and Docker answers a missing bind-mount
# source by creating a directory at the target rather than failing cleanly.
#
# This path was once retired as unimplementable — no repo contained an
# interceptor MCP server, so the agent had no working browser driver at all.
# That premise turned out to be wrong: Interceptor ships a real `mcp serve`
# subcommand. It is kept opt-in rather than restored as the default because it
# depends on host state this repo neither controls nor can test in CI, whereas
# the `browser` service is self-contained. It earns its keep by inheriting
# sessions the operator is already logged into, with no noVNC step at all.
#
# Either way, NOTHING that renders a page is installed below — do not "fix" the
# absence of a browser in this image by adding one back.

FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    NODE_ENV=production

# ca-certificates: TLS for the claude CLI and for this container's calls to
# ${TRUTHCV_MCP_URL}. tzdata: RUN_AT (docker-compose.yml) is a container-TZ
# schedule, same as the retired Jobs project's RUN_AT. jq: agent/daily-apply.sh
# renders the entire job-profile / criteria / salary prompt block with it, and
# now aborts the run outright when it is missing rather than silently dropping
# every configured profile.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tzdata jq \
 && rm -rf /var/lib/apt/lists/*

# The claude CLI — install command carried over unchanged from the Jobs
# project's docker/Dockerfile. @playwright/mcp is deliberately NOT installed
# here: it runs in the `browser` service (browser/Dockerfile), and this image
# only needs to TALK to it over HTTP, which the claude CLI does from
# agent/mcp.json's `browser` server entry. See the BROWSER STRATEGY note above.
RUN npm install -g @anthropic-ai/claude-code

# node:22-bookworm-slim already ships a `node` user at UID 1000 — reuse it
# rather than create a second UID-1000 account, which fails (same reasoning
# as the Jobs project's docker/Dockerfile).
# /app/runs is created HERE, owned by node, so the named volume that
# docker-compose.yml mounts over it inherits that ownership — a volume mounted
# onto a path the image does not contain is created root-owned, and the agent
# (USER node) could then not write its run logs.
# /opt/interceptor/bin is the mount target for the host interceptor binary under
# the opt-in `interceptor` driver (docker-compose.interceptor.yml). It is created
# here, empty, so that the directory exists in the image whether or not that
# overlay is in use — costing nothing under the default `browser` driver.
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
# The scheduling loop and control-server HTTP surface. entrypoint.sh execs
# this as its final step, so the image does not start without it.
COPY --chown=node:node agent/supervisor.js   /app/agent/supervisor.js
# The smoke test is shipped IN the image, not just kept in the repo: it is run
# via `--entrypoint /app/agent/smoke-test.sh` against the built container, and
# its whole point is to test the image as shipped (agent/README.md).
COPY --chown=node:node agent/smoke-test.sh   /app/agent/smoke-test.sh
RUN chmod +x /app/agent/daily-apply.sh /app/agent/entrypoint.sh /app/agent/smoke-test.sh

USER node
WORKDIR /app/agent

ENTRYPOINT ["/app/agent/entrypoint.sh"]
