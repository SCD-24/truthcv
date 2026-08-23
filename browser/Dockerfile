# Containerised headful Chromium MCP server for TruthCV's unattended agent.
#
# This container runs Chromium (supplied by the mcr.microsoft.com/playwright
# base image) under Xvfb on a virtual display, with x11vnc and noVNC for
# remote observation. The @playwright/mcp server exposes a stable HTTP tool
# surface (browser_navigate, browser_click, etc.) that the agent reaches over
# the compose network.
#
# WHY A SEPARATE BROWSER CONTAINER:
# The agent's own container (agent/Dockerfile) deliberately installs no browser.
# This separation ensures:
#   - A browser crash (Chromium OOM, a hung tab, a bot-detection block) does not
#     take down the agent loop — the agent reconnects to the browser service
#     or waits for it to restart.
#   - The agent image stays small and focussed; the browser stack is isolated
#     and replaceable.
#   - A persistent /browser-profile volume survives restarts, so a one-time
#     login (CAPTCHA, SMS, MFA) established in the noVNC viewport lasts for
#     all future runs.
#   - The browser and all its system dependencies (Xvfb, X11 libraries, etc.)
#     are shipped by the official Playwright image, not built here — we inherit
#     exactly the tested environment the Playwright team publishes.

FROM mcr.microsoft.com/playwright:v1.49.0-noble

ENV DEBIAN_FRONTEND=noninteractive \
    NODE_ENV=production

# Install additional tools:
#   xvfb:       Virtual X11 display server (Chromium runs headful here)
#   x11vnc:     VNC server over the X11 display (observe running tests)
#   novnc:      Browser-based VNC client (accessible as http://localhost:7900)
#   websockify: WebSocket-to-socket bridge, required by noVNC
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11vnc novnc websockify \
 && rm -rf /var/lib/apt/lists/*

# Install @playwright/mcp globally — the Playwright image ships node,
# so `npm install -g` works immediately.
RUN npm install -g @playwright/mcp@latest

# Then install the Chromium build that THIS @playwright/mcp expects.
#
# The base image ships the browsers matching its own tag (v1.49.0 ->
# chromium-1148), but @playwright/mcp@latest bundles its own, newer
# playwright-core and looks for that version's build (chromium-1237 at the time
# of writing). The two drift apart silently: the MCP server starts and answers
# its healthcheck, so the container reports healthy, and only an actual
# browser_navigate fails — "expected executable at
# /ms-playwright/chromium-1237/chrome-linux64/chrome". A whole unattended run
# reaches zero applications that way.
#
# Installing through the MCP package's own playwright-core is what keeps the
# two in step: it resolves the version the server will actually ask for, so
# this stays correct when the package updates. PLAYWRIGHT_BROWSERS_PATH puts it
# beside the base image's copies rather than in root's home.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npx --yes playwright-core@$(node -p "require('/usr/lib/node_modules/@playwright/mcp/node_modules/playwright-core/package.json').version") install chromium \
 && rm -rf /root/.npm

# Create mount points:
#   /browser-profile: persistent Chromium user profile (named volume)
#   /app/data:        read-only mount of the app's data directory
#                     (so Playwright's browser_file_upload can resolve
#                      paths get_canonical_cv returns, e.g. /app/data/canonical_cv.pdf)
RUN mkdir -p /browser-profile /app/data

# Expose ports:
#   8931: @playwright/mcp HTTP server (internal to compose network)
#   7900: noVNC (web-based VNC viewer, useful for debugging/manual login)
EXPOSE 8931 7900

# Entrypoint: starts Xvfb, x11vnc, noVNC and @playwright/mcp.
COPY browser/entrypoint.sh /browser/entrypoint.sh
RUN chmod +x /browser/entrypoint.sh

ENTRYPOINT ["/browser/entrypoint.sh"]
