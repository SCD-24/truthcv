# Distributing TruthCV to non-technical colleagues — design

Status: accepted, not implemented.

## Goal

A colleague who has never used a terminal can run the whole system —
wizard, ledger and the unattended application agent — on their own
laptop, on macOS, Windows or Linux.

Success is: install Docker Desktop, unzip, double-click, then finish
setup in the browser. No terminal, no text editor, no YAML.

## Runtime model

Each colleague runs the full stack locally on their own machine. Their
data, credentials and ATS sessions never leave it.

This is the decision every other part of the design rests on. A single
shared instance was rejected: the app is single-user by construction —
one `truth.yaml`, one data directory, no login, and
`GET /api/download/{name}` serves the data root by bare filename with
no authentication. Sharing one instance would mix colleagues' CVs,
ledgers and browser sessions together. Making it multi-user is a
different and much larger project.

## What already works

Most of the setup burden in `README.md` is not inherent. The
capabilities already exist as browser flows:

- **Claude sign-in.** `POST /api/auth/claude/login` and
  `/api/auth/claude/complete` (`api/routes.py:1452`) implement a
  subscription OAuth flow. A colleague can sign in with a Claude
  subscription and never obtain an API key or set up billing.
- **Identity answers.** `PUT /api/profile/answers` (`api/routes.py:967`)
  writes the same file as the README's
  `docker compose run --rm -v … python -m truth.answers` incantation.
- **Agent credentials.** The agent fetches its LLM credential from the
  app at run time (`GET /api/agent/llm-credentials`,
  `api/routes.py:1042`), so the agent container needs no sign-in of its
  own.

All three are gated behind one thing: `ENCRYPTION_KEY` must be set, or
`secretstore.encryption_available()` (`secretstore/__init__.py:27`)
returns false and Settings → Accounts is disabled. That single manual
step forces every other manual step. Removing it is most of the work.

## Architecture

Three additions. No changes to existing application code beyond the
compose port mappings.

| Artifact | Purpose |
|---|---|
| `scripts/launch/truthcv.command` (macOS), `truthcv.bat` (Windows), `truthcv.sh` + `truthcv.desktop` (Linux) | Double-clickable entry point. Preflight, bootstrap, `docker compose up -d`, wait, open browser. |
| `scripts/launch/bootstrap.py` | Secret generation, `.env` management, port selection. One implementation, run in a container. |
| `/setup` route in `web/` | Guided first-run wizard over existing endpoints. |

### Bootstrap runs in a container

The launcher scripts are thin per-OS shims. All real logic lives in
`bootstrap.py`, executed as:

```
docker run --rm -v "<repo>:/work" -w /work python:3-alpine python scripts/launch/bootstrap.py
```

macOS and Linux ship Python 3; Windows does not. The alternatives were
to make Windows users install Python — a prerequisite likely to stop
the exact audience this is for — or to maintain the same logic twice,
in Python and PowerShell, where the copies drift and the divergence
surfaces only on a colleague's machine. Docker is already a hard
requirement, so it is the one interpreter guaranteed present on all
three platforms.

`python:3-alpine` is used rather than the app's own image, which does
not exist before the first build. Everything bootstrap needs is
standard library: a Fernet key is
`base64.urlsafe_b64encode(os.urandom(32))`, identical to what
`api/genkey.py` produces, and the token is `secrets.token_hex(32)`.
No packages are installed.

On macOS and Linux the container runs with `--user "$(id -u):$(id -g)"`
so files it creates are owned by the user, not root. Without this the
generated `.env` reproduces the `PermissionError` the README already
documents for the data volume.

## `.env` handling

Bootstrap must never destroy an existing configuration — the
maintainer's own or a colleague's. The rules are absolute:

1. **Absent** — create from `.env.example` with `ENCRYPTION_KEY` and
   `AGENT_API_TOKEN` filled in.
2. **Present, both keys set and non-blank** — read it, write nothing,
   proceed. The file is not opened for writing.
3. **Present, one or both missing or blank** — copy to
   `.env.backup-<UTC timestamp>`, then **append** only the missing keys
   in a marked block at the end of the file.
4. **Never** overwrite, reorder, rewrite or delete. No existing line is
   modified, so comments and formatting survive byte-for-byte. Backups
   are never removed.

Bootstrap prints exactly which keys it added and where the backup went.
Re-running it on a complete `.env` is a no-op.

Values are generated per machine, so no two colleagues share a secret.

### Why `AGENT_API_TOKEN` cannot come from the UI

`AGENT_API_TOKEN` is not a provider credential. It is the shared secret
between the app and the agent container, used in both directions: the
app sends it as `X-Agent-Token` when triggering, cancelling or polling a
run (`api/routes.py:1107`), and the agent presents it to
`GET /api/agent/llm-credentials` (`api/routes.py:1048`) — the route that
returns the Claude credential the user set in Connections.

It therefore cannot be supplied through Connections: holding it is the
precondition for reading them.

It also cannot be generated by the app at first start. Both sides read
it from `os.environ`, and the agent is a separate container whose
environment is fixed when `docker compose up` creates it. By the time
the UI is reachable both containers have booted. The agent deliberately
does not mount the data volume, so there is no shared file to pass it
through either. Environment is the only channel, and it must be
populated before the stack starts.

`agent/entrypoint.sh:57` aborts the agent at startup when neither
`ANTHROPIC_API_KEY` nor `AGENT_API_TOKEN` is set, so a bare
`docker compose up` with no `.env` does not degrade — the agent refuses
to run.

### Who supplies what

| Secret | Source | When |
|---|---|---|
| `ENCRYPTION_KEY` | Bootstrap, generated | Before first `compose up` |
| `AGENT_API_TOKEN` | Bootstrap, generated | Before first `compose up` |
| `APP_PORT` | Bootstrap, probed | Before first `compose up` |
| Claude credential | Colleague, Connections UI | After launch, in the browser |
| Identity answers | Colleague, Settings UI | After launch, in the browser |

Only the bottom two reach the user, and both are browser forms.

## Ports

The default host port is **5627** for the app and **5628** for the noVNC
viewport.

Only the host side of each mapping changes. Container-internal ports
stay at 8080 and 7900 permanently:

```yaml
ports:
  - "${APP_PORT:-5627}:8080"
  - "${NOVNC_HOST_PORT:-5628}:7900"
```

| Reference | Kind | Changes |
|---|---|---|
| `docker-compose.yml:5` `"8080:8080"` | host publish | Yes, left side |
| `docker-compose.yml:47` `"7900:7900"` | host publish | Yes, left side |
| `Dockerfile:52` `ENV PORT=8080`, `EXPOSE 8080` | in-container | No |
| `docker-compose.yml:117` `TRUTHCV_MCP_URL=http://app:8080/mcp` | compose network | No |
| `agent/mcp.json` `http://app:8080/mcp` | compose network | No |
| `browser/entrypoint.sh:20` `NOVNC_PORT` | in-container | No |
| `browser/Dockerfile:71` `EXPOSE 8931 7900` | in-container | No |
| `api/config.py:20` `PORT` default | in-container | No |
| `web/vite.config.ts:17` `localhost:8080` | local dev only | No |
| `AGENT_CONTROL_PORT=9099` | in-network, unpublished | No |

The agent reaches the app over the compose network at
`http://app:8080/mcp`, which is independent of what the host publishes.
A colleague can serve on 5627 while the containers keep talking on 8080.

### Name collision

`browser/entrypoint.sh:20` already reads an env var named `NOVNC_PORT`
for the port *inside* the container. Reusing that name for the host side
would change the internal port too and leave the mapping pointing at
nothing. The host-side variables are therefore `APP_PORT` and
`NOVNC_HOST_PORT`, deliberately distinct from `PORT` and `NOVNC_PORT`.

### Verified non-breakages

- **DNS-rebinding guard.** `api/main.py:36-38` sets
  `enable_dns_rebinding_protection=False`, so there is no host allowlist
  for a new port to fail.
- **Claude OAuth.** `connections/auth/claude.py:28` redirects to
  `https://platform.claude.com/oauth/code/callback` and the user pastes
  the code back. No localhost redirect, so port-independent.
- **CORS.** Production serves the SPA same-origin from the API, so a
  changed host port leaves origin and API identical. The `CORS_ORIGINS`
  default of `http://localhost:5173` (`api/config.py:15`) is the Vite dev
  origin and is unrelated.

### Port selection

1. If `APP_PORT` is present in `.env`, reuse it. Sticky, so bookmarks
   keep working. Never re-probe merely because it is busy.
2. When unset, probe upward from 5627. The first free port wins and is
   appended to `.env` under the rules above.
3. Before treating a busy stored port as a conflict, check whether this
   project's own compose stack holds it (`docker compose ps`). Our own
   running container is the normal case, not a collision.
4. A stored port genuinely held by something else stops the launch with
   an explanation and an offered alternative. A bookmarked port is never
   silently moved.

`NOVNC_HOST_PORT` follows the same rules, probing upward from 5628.

Ports are allocated in order — app first, then noVNC — and each probe
skips ports already allocated in this run as well as those already
bound. Without that, an app falling back to 5628 would collide with the
noVNC default.

## First-run wizard

On load the app computes readiness from four existing read-only routes
and redirects to `/setup` when any step is incomplete:

| Step | Signal | Route | Required for |
|---|---|---|---|
| Claude connected | `subscriptionConnected` or `anthropicKeySet` | `GET /api/auth/status`, `GET /api/settings` | Everything |
| Truth file built | `hasProfile` | `GET /api/profile` | Everything |
| Identity seeded | required answer fields non-blank | `GET /api/profile/answers` | Agent runs |
| Agent targets set | `targetCompanies` non-empty | `GET /api/agent/config` | Agent runs |

Each step is one page with one job, a sentence explaining why it is
needed, and a skip control where skipping is survivable. Steps 1 and 2
are required to use the app at all; steps 3 and 4 are required only
before the agent submits anything, matching the existing refusal in
`agent/RUNBOOK.md` §5.

Step 3 replaces the README's
`docker compose run --rm -v "$(pwd)/answers.local.yaml:…"` command
entirely — same file, via `PUT /api/profile/answers`.

Step 4 links to the noVNC viewport on the resolved `NOVNC_HOST_PORT`,
framed as "sign in to the job sites you use, once". Those sessions
persist on the `browser-profile` volume.

No aggregate `/api/setup-status` endpoint is added. The four calls the
frontend already makes are sufficient, and a fifth route would be a
second place for the definition of "ready" to drift.

## Distribution

Images are not published. The first launch builds from source.

- The release artifact is a zip built by `scripts/release.sh` using
  `git archive`, which can only emit tracked files. `.env`, `data/` and
  `answers.local.yaml` are all gitignored and therefore structurally
  excluded — not excluded by a list someone must maintain.
- The script then asserts the built zip contains none of those three
  paths and fails loudly if it does. An ad-hoc `zip -r` of the working
  directory would ship the maintainer's API keys, ledger and
  `secrets.enc`; `git archive` cannot, and the assertion proves it.
- The first launch shows an honest progress window: "Setting up TruthCV
  for the first time. This takes about 10 minutes and only happens
  once." Later launches go straight to `compose up -d`. A double-click
  that silently appears hung for ten minutes reads as broken and gets
  killed.
- `SETUP.md` is written for a non-technical reader: install Docker
  Desktop, unzip, double-click. Screenshots, no commands. `README.md` is
  unchanged and remains the maintainer's document.

## Error handling

The launcher reports these in plain language, never as a stack trace:

| Failure | Message |
|---|---|
| Docker not installed | "TruthCV needs Docker Desktop", with a download link |
| Docker installed but not running | "Docker Desktop isn't running. Start it, then try again." |
| Chosen port held by another program | Names the port and the alternative offered |
| Build fails | Keeps the log, names the file, does not vanish |
| App not up within the timeout | "Still starting — open http://localhost:<port> in a minute" |

## Testing

`bootstrap.py` gets unit tests for the `.env` rules, which are where a
bug destroys a real file:

- absent, complete, and partial `.env`
- comments and formatting preserved byte-for-byte
- backup created before any append
- idempotent on re-run
- port sticky when stored, probed when absent
- own-stack detection distinguished from a foreign port holder

The launcher scripts get a manual smoke check per platform. A
double-click on three operating systems is not meaningfully automated
here.

## Known constraints

- **Docker Desktop remains a prerequisite.** Nothing in this design
  removes it. If it proves to be the barrier that stops colleagues, the
  answer is hosting, not packaging.
- **ATS sign-ins stay manual.** SSO, CAPTCHA and SMS MFA are the point
  of the headful browser; they cannot be automated away. They are
  one-time per site and happen in a browser window.
- **Gmail sync and dynamic ports.** `gmailsync/` and
  `connections/auth/gmail.py` exist but no route references them, so
  nothing breaks today. `connections/auth/gmail.py:59` takes
  `start_login(redirect_uri)`, and Google requires redirect URIs to be
  registered exactly. Wiring it up will need a fixed port or a
  registered range of them. This is a constraint on that future work,
  not on this design.
