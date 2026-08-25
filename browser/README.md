# Browser Container

The `browser` service in docker-compose.yml runs a headful Chromium instance under Xvfb, exposed via @playwright/mcp over HTTP on port 8931 (internal to the compose network). The agent (agent/Dockerfile) reaches this container to automate job applications.

## noVNC Viewport

The port is not published to the host. Observe what Chromium is doing, or
drive it, from **Agents page → Site sign-ins** in TruthCV, which relays the
viewport through the app's origin-checked WebSocket route
(`WS /api/browser/session/stream`).

This is useful for:
- Watching an application or screening in real time
- Completing a one-time login (CAPTCHA, SMS MFA, SSO challenge) to establish a session
- Debugging why a site loaded unexpectedly or a click did not work

The viewport itself requires no password (x11vnc runs `-nopw`) and connects
directly to the Xvfb display the browser runs on — reaching it directly, not
through the app's relay, would give unauthenticated control of a browser that
may hold live ATS and email sessions, which is why it is not published.

## Profile Persistence

Chromium's user profile is mounted at `/browser-profile` as a named Docker volume (`browser-profile:`). This means:
- A login established once (clicking "Remember this device", accepting cookies, etc.) persists across container restarts
- The browser does not start from a blank profile every run — sessions, cookies, and plugin state all survive
- If you need to clear the profile entirely, run `docker volume rm truthcv_browser-profile` (the `truthcv_` prefix is your compose project name)

## Data Volume

The read-only mount `${DATA_DIR:-./data}:/app/data:ro` exists so Playwright's `browser_file_upload` tool can resolve filesystem paths. When the agent calls `get_canonical_cv`, the tool returns an object including `path: /app/data/canonical_cv.pdf`. The browser container sees that same path because it mounts the data directory read-only at the same location the app service uses internally.

This is why the browser container mounts the data volume, but the agent container deliberately does not — see agent/README.md.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BROWSER_MCP_PORT` | `8931` | Port the @playwright/mcp HTTP server listens on (internal to compose) |
| `BROWSER_PROFILE_DIR` | `/browser-profile` | Mounted path of the persistent Chromium profile |
| `TZ` | `UTC` | Container timezone (affects logs and any time-based logic) |

## Risk: Bot Detection

A containerised browser presents a datacenter IP address and a fresh Chromium fingerprint that differs from your personal machine. Some ATS platforms and application sites use bot-detection logic (Cloudflare, Perimeter X, etc.) and may silently block or challenge a containerised browser more aggressively than they would your own.

This is documented in agent/RUNBOOK.md §5 "Browser tooling is whatever this environment provides", which flags that §5 "Verify the submission actually landed" matters more here for exactly this reason. Mitigations:
- Use the noVNC viewport (Agents page → Site sign-ins) to watch runs in real time and spot when a site challenges or blocks the browser
- Manually complete any one-time login or CAPTCHA from the Site sign-ins flow (it persists to the profile volume)
- Monitor your email for any "Verify this login" challenges and complete them as they arrive

## History

An alternative driver, reaching the operator's real, already-logged-in browser on the host via a stdio MCP server dialing a bind-mounted unix socket to a host daemon, was previously offered as an opt-in Compose overlay. It has been removed, leaving the containerised browser as the only driver.

The containerised browser is simpler (no host daemon to run), more reproducible (Chromium ships with the image), and achieves the isolation the separate-container architecture was meant to provide: a browser crash cannot take down the agent loop.
