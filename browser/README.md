# Browser Container

The `browser` service in docker-compose.yml runs a headful Chromium instance under Xvfb, exposed via @playwright/mcp over HTTP on port 8931 (internal to the compose network). The agent (agent/Dockerfile) reaches this container to automate job applications.

## noVNC Viewport

The port is not published to the host. Reach the viewport from the **Job
boards** page in TruthCV, which relays it through the app's origin- and
peer-checked WebSocket route (`WS /api/browser/session/stream`) and only
while a sign-in session is open.

It is for signing in by hand:
- Completing a one-time login (CAPTCHA, SMS MFA, SSO challenge) to establish a session
- Checking, during that sign-in, why a page did not load or a click did not work

**You cannot watch a run in progress.** A run and a sign-in session cannot
both hold the Chromium profile, so the session is refused while a run is
going and an open session is evicted when one starts — the run wins, by
design. Diagnose a run from its log under the `agent-runs` volume and from
the application ledger, not from the viewport.

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

**The mount alone is not sufficient.** @playwright/mcp (pinned in browser/Dockerfile) restricts `browser_file_upload` to paths under its own `--output-dir` or the MCP client's advertised workspace root — our agent's HTTP JSON-RPC client advertises no root, and `--output-dir` defaults to a private scratch directory that does not cover `/app/data`. entrypoint.sh passes `--output-dir "$BROWSER_UPLOAD_ROOT_DIR"` (default `/app`, which contains `/app/data`) specifically so the mount above is actually reachable — without it, `browser_file_upload` rejects `/app/data/canonical_cv.pdf` as "outside allowed roots" even though the file is right there. `/app` is used instead of `/app/data` itself because the mount is read-only and `--output-dir` must also stay writable for screenshots and traces.

This is why the browser container mounts the data volume, but the agent container deliberately does not — see agent/README.md.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BROWSER_MCP_PORT` | `8931` | Port the @playwright/mcp HTTP server listens on (internal to compose) |
| `BROWSER_PROFILE_DIR` | `/browser-profile` | Mounted path of the persistent Chromium profile |
| `BROWSER_UPLOAD_ROOT_DIR` | `/app` | Passed to @playwright/mcp's `--output-dir`, which doubles as its `browser_file_upload` allow-list root in this version (0.0.79 — see browser/Dockerfile). Must cover `/app/data` or CV uploads are rejected as outside allowed roots. |
| `TZ` | `UTC` | Container timezone (affects logs and any time-based logic) |

## Diagnosing a Stalled Attended Sign-In

If clicking or typing in the attended sign-in viewport appears to do nothing,
the browser container now forwards Chromium's own stdout/stderr under a
`chrome:` prefix — `docker compose logs browser` is the first stop. Three
signatures are worth looking for:

- A renderer crash / out-of-memory line from Chromium itself — this was the
  usual cause of a silently dead viewport before `--disable-dev-shm-usage`
  (session-server.js) and `shm_size: "2gb"` (docker-compose.yml) were added;
  seeing one after this change means the mitigation did not cover the case.
- An `eviction deadline reached` line — the agent took the browser back
  mid-sign-in because `SESSION_GRACE_MS` (default `180000`ms) elapsed. Finish
  the sign-in faster, or raise `SESSION_GRACE_MS` together with the agent's
  `SESSION_EVICT_TIMEOUT` (see the `browser`/`agent` service comments in
  docker-compose.yml).
- A clean page with no Chromium complaint at all — points at a site-side
  anti-bot challenge (see below) rather than this container.

## Risk: Bot Detection

A containerised browser presents a datacenter IP address and a fresh Chromium fingerprint that differs from your personal machine. Some ATS platforms and application sites use bot-detection logic (Cloudflare, Perimeter X, etc.) and may silently block or challenge a containerised browser more aggressively than they would your own.

This is documented in agent/RUNBOOK.md §5 "Browser tooling is whatever this environment provides", which flags that §5 "Verify the submission actually landed" matters more here for exactly this reason. Mitigations:
- Read the run log and the application ledger for postings that were reached but never submitted — a challenge or block shows up there, since the viewport cannot be watched during a run
- Manually complete any one-time login or CAPTCHA from the Site sign-ins flow (it persists to the profile volume), which is also the one time you can see the site as the agent's browser does
- Monitor your email for any "Verify this login" challenges and complete them as they arrive

## History

An alternative driver, reaching the operator's real, already-logged-in browser on the host via a stdio MCP server dialing a bind-mounted unix socket to a host daemon, was previously offered as an opt-in Compose overlay. It has been removed, leaving the containerised browser as the only driver.

The containerised browser is simpler (no host daemon to run), more reproducible (Chromium ships with the image), and achieves the isolation the separate-container architecture was meant to provide: a browser crash cannot take down the agent loop.
