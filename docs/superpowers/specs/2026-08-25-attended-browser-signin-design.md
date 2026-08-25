# Attended browser sign-in — design

Status: accepted, not implemented.

## Goal

An operator can sit down at a time of their choosing, open a browser
they can drive, sign in to a job site, and have that session persist
for every later unattended run.

Today they cannot. The containerised browser has no attended mode.

## The problem

`browser/entrypoint.sh` starts Xvfb, x11vnc, websockify and
`@playwright/mcp`. It never starts a browser. Chromium is launched
lazily by the MCP server on the first `browser_*` tool call and exits
with the run. Measured on a healthy idle container: zero Chromium
processes.

So the noVNC viewport at `http://localhost:5628` shows an empty X root
whenever a run is not in progress. Every document that instructs the
operator to sign in there — `README.md`, `browser/README.md`,
`agent/README.md` — describes something that can only be done *during*
a run, while the agent is competing for the same keyboard.

Three conditions compound it:

- **No window manager.** `browser/Dockerfile` installs `xvfb x11vnc
  novnc websockify` and nothing else. Chromium's windows are unmanaged:
  no title bar, no move, resize, raise or close. SSO flows open a second
  top-level window for the identity provider, which lands stacked over
  or under the first with no way to switch between them.
- **No route from the app.** The address appears only in README files.
  `NOVNC_HOST_PORT` is host-side Compose state (`launcher/ports.py:16`)
  exposed through no API, which is the gap
  `docs/superpowers/plans/2026-08-25-first-run-wizard.md:710` records as
  unresolved.
- **No signal.** `agent/RUNBOOK.md`, `agent/prompt.md` and
  `agent/daily-apply.sh` contain no mention of login, SSO, CAPTCHA or
  MFA. A run that hits a login wall reports nothing that identifies
  which site needs attention.

## Which sites need a sign-in

`agentconfig/dorks.py:15` enumerates the platforms the agent visits, and
each job profile selects from them via `preferred_sources`. They divide
three ways, and the division drives the design:

| Platform | Login | Consequence |
|---|---|---|
| Ashby, Greenhouse, Lever, Personio | None — public application forms | Nothing to set up |
| LinkedIn | One account, knowable in advance | A setup step handles it |
| Workday (`*.myworkdayjobs.com`) | An account per employer tenant | Cannot be enumerated ahead of time |

There is no "sign in to Workday": each employer runs its own tenant and
wants a separate account created there. SuccessFactors and Taleo behave
the same way. This tail is the bulk of the burden and only a reactive
mechanism can reach it.

These login requirements are drawn from knowledge of those platforms,
not from anything this repository asserts. Confirm them against real
postings before relying on the table.

## Decisions

1. **One mechanism, two callers.** A single "open a browser I can drive
   at this URL" primitive, driven both by a proactive setup list and by
   a reactive queue of sites the agent could not get into.
2. **The app proxies the viewport.** One origin, app-owned chrome
   around it — not a link to a second port.
3. **Runs win over sign-in sessions.** Unattended reliability is never
   traded away, with a bounded grace period so the operator is warned
   rather than interrupted.
4. **The agent's experience is the only source of truth** for whether a
   site needs a sign-in. No probing, no operator-asserted flags.
5. **The agent never creates an account.** Registration walls are
   reported, not passed.

## Components

### `browser/session-server.js` (new)

A control server inside the `browser` container on port 8932, in-network
only and never published, mirroring `agent/supervisor.js`. It holds one
piece of state: the current session, or none.

- `GET /session` — state.
- `POST /session {url}` — launch.
- `POST /session/close` — kill and clear.
- `POST /session/evict` — set an eviction deadline (see Lifecycle).

`POST /session` refuses unless all three hold, checked in order:

1. No session is already open. Refusal carries the open session's URL so
   the UI can offer to return to it rather than silently stealing it.
2. `supervisor.js GET /status` reports idle. **An unreachable supervisor
   refuses**, matching how `daily-apply.sh` already fails closed on an
   unreachable config API rather than assuming a safe state.
3. No Chromium currently holds `/browser-profile`. Launching a second
   browser on that profile is the documented "Browser is already in use"
   failure that `browser/entrypoint.sh` exists to clean up after.

### `browser/Dockerfile`

Add a window manager — there is none today — and the session server.
Chromium is already present in the image. `EXPOSE 8931 7900` gains 8932.

### `docker-compose.yml`

- Stop publishing `5628:7900`. The viewport becomes in-network only.
- Bind the app to loopback: `"127.0.0.1:${APP_PORT:-5627}:8080"`. This
  changes the host publish only. The agent reaches the app at
  `http://app:8080` over the Compose network, which is unaffected.

### `api/routes.py`

- `/api/browser/session` GET/POST/DELETE, forwarding to the session
  server using the `_forward_to_supervisor` idiom at line 1151.
- `GET /api/browser/signin-queue` (see Queue).
- `WS /api/browser/session/stream`, relaying to
  `ws://browser:7900/websockify`. The app has no WebSocket route today;
  `uvicorn[standard]` already carries the support.

### Web

- A "Site sign-ins" section on the Agents page.
- A new route `/browser-session`, reached by button rather than from the
  nav rail, as `/applications/:id/filled-form` already is.
- New dependency `@novnc/novnc`. The alternative — proxying the browser
  container's bundled noVNC assets through the app — is more moving
  parts for a worse result.

### Agent

Two optional arguments on an existing tool and one RUNBOOK rule. No new
tool, no new store.

## Lifecycle

A session is a live process handle. It is not persisted and does not
survive a container restart; the browser dies with the container.

There is no idle timeout on an open session by itself. A forgotten
session cannot cost a run, because a run evicts it.

**Eviction.** `POST /session` checks the supervisor at a moment in time,
so a run can start afterwards. The run is therefore the other half of
the interlock: `daily-apply.sh` gains a precondition that calls
`POST /session/evict`, which sets a deadline three minutes out. The
session page shows a countdown — "the agent needs the browser in
2:47 — finish up" — and the session server kills the session at zero.
The run polls `GET /session` until the browser is free, then proceeds.

The operator is warned; the run still happens.

## Queue

Most of this already exists. `report_apply_failure(screening_id, error)`
(`agenttools/tools_ledger.py:520`) records why an application could not
complete and leaves the item queued for the next run. A login wall is
exactly that. What is missing is that `error` is free text, so nothing
can filter for login walls or know which URL to open.

1. **`screening/model.py`** — two fields beside `apply_attempts` and
   `apply_error`: `apply_blocker: str = ""` (empty, or `"login_required"`)
   and `signin_url: str = ""`. Defaulted, so existing persisted records
   load unchanged.
2. **`screening/store.py:161`** — `record_apply_failure(screening_id,
   error, blocker="", signin_url="")`. Additive; existing callers are
   unaffected.
3. **`agenttools/tools_ledger.py:520`** and the tool description at
   `agenttools/mcp_app.py:70` — the same two optional arguments, and
   wording that says when to set them.
4. **`agent/RUNBOOK.md`** — a rule in the apply section: when a form
   sits behind a sign-in or a registration wall, do not create an
   account and do not guess credentials. Call `report_apply_failure`
   with `blocker="login_required"` and the login page URL, then move to
   the next posting.
5. **`api/routes.py`** — `GET /api/browser/signin-queue`, derived from
   queued screenings where `apply_blocker == "login_required"`,
   **deduplicated by full host**. The unit is
   `acme.wd3.myworkdayjobs.com`, not `myworkdayjobs.com`; twenty roles
   at one tenant is one entry. Each entry carries the host, a label, the
   number of postings waiting behind it, when it was last hit, and the
   `signin_url`.

## UI

**Agents page — "Site sign-ins"**, two groups:

- **Needs attention**, from `GET /api/browser/signin-queue`. Rows read
  "acme.wd3.myworkdayjobs.com — 4 postings waiting, last blocked
  25 Aug", each with a Sign in button. Empty most of the time, and
  empty is the good state.
- **Your job boards**, from the profiles' `preferred_sources` mapped
  through `SOURCE_DOMAINS`. No status indicators: the agent's
  experience is the only truth, so these are an invitation to sign in
  ahead of time, nothing more.

A sign-in count badge on the Agents nav item follows the existing
`pendingApprovals` pattern in `web/src/nav/SideNav.tsx`.

**`/browser-session`** — an app bar carrying the host name, Reload and
Done, with the `@novnc/novnc` canvas beneath. Five states: starting,
live, evicting (countdown), refused (`409` — "the agent is applying
right now, try again in a few minutes"), and closed.

Done must not claim success. The wording is "Closed. If it worked, the
next run will get through; if not, this site will show up here again."
Nothing stronger is supportable, because nothing checks.

## Security

**The app has no user authentication.** The only guard in
`api/routes.py` is `AGENT_API_TOKEN`, protecting one agent-facing
endpoint. CORS is configured at `api/main.py:124`, and CORS is not
authentication.

Proxying the viewport through the app therefore consolidates two
exposed surfaces into one. It does not place the viewport behind an
auth boundary, because there is none to place it behind. Three measures
follow, and the second and third are load-bearing:

1. **Unpublish `5628:7900`.** The browser is no longer independently
   reachable.
2. **Bind the app to loopback.** `"${APP_PORT:-5627}:8080"` listens on
   every interface today. The launcher opens `localhost`, so this
   matches real use. It is a behaviour change for anyone who reaches
   TruthCV from another device on their network. Without it, adding a
   remote-control surface makes the current exposure materially worse.
3. **Origin-check the WebSocket relay.** WebSocket connections are not
   subject to the same-origin policy and CORS does not apply to them.
   Without an explicit `Origin` check in
   `/api/browser/session/stream`, any web page the operator visits
   while a session is open can connect to that socket and drive a
   browser logged into their accounts. The relay rejects any `Origin`
   that is not the app's own, and refuses to relay when no session is
   open.

Real authentication on the app is the proper fix and is out of scope
here. It is the reason measure 2 carries so much weight, and it is a
known limit of this design rather than an oversight.

## Testing

- **pytest** — queue derivation and host dedup; the new routes; the
  `Origin` rejection; `record_apply_failure`'s new arguments against
  existing persisted records.
- **vitest** — the Agents page section in both its empty and populated
  states; the five session-page states.
- **`browser/`** — the session server refusing on each of its three
  preconditions.

Not testable here, as today: an actual sign-in against a real employer.

## Consequences

- `NOVNC_HOST_PORT` (`launcher/ports.py:16`,
  `launcher/__main__.py:45`) becomes dead once the port is unpublished.
- The first-run wizard gap at
  `docs/superpowers/plans/2026-08-25-first-run-wizard.md:710` dissolves:
  the viewport is an in-app route, so there is no host port for the
  frontend to learn.
- `README.md`, `browser/README.md` and `agent/README.md` all instruct
  the operator to visit `http://localhost:5628`. All three need
  rewriting to the in-app flow.

## Out of scope

- **Account registration.** The agent reports registration walls and
  never passes them. Automating this would need a credential lifecycle,
  email verification through `gmailsync`, and an agent creating accounts
  in the operator's name unsupervised. `secretstore` and the
  per-company tracking addresses from `get_profile_answers(company=…)`
  make it reachable later; nothing here forecloses it.
- **App authentication.** See Security.
- **Signed-in status indicators.** Excluded by the decision that the
  agent's experience is the only source of truth.
