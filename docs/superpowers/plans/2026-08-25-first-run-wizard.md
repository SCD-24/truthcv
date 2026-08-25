# First-Run Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A colleague who has just launched TruthCV for the first time is walked through connecting Claude, uploading their LinkedIn PDF, filling in their details and choosing target companies — in the browser, with no terminal.

**Architecture:** Readiness is a pure function over four existing read-only endpoints; no new backend route is added. `App` redirects to `/setup` while any blocking step is incomplete. Each step is one page delegating to the client functions that already exist.

**Tech Stack:** React 18, TypeScript, MUI 9, react-router-dom 6, vitest.

**Spec:** `docs/superpowers/specs/2026-08-25-nontechnical-distribution-design.md`

## Global Constraints

- **No new backend endpoints.** Readiness comes from `GET /api/auth/status`, `GET /api/profile`, `GET /api/profile/answers` and `GET /api/agent/config`, all of which already have client wrappers: `listConnections`, `getProfile`, `getProfileAnswers`, `getAgentConfig`. A fifth route would be a second place for "ready" to drift.
- **Two blocking steps only.** `connect` and `truth` are required to use the app. `identity` and `targets` are required only before the agent submits anything, matching the existing refusal in `agent/RUNBOOK.md` §5, and must be skippable.
- The noVNC link uses the **host** port, which varies per machine. Never hard-code 7900 or 5628 — derive it, or link relatively.
- Follow the existing frontend conventions: MUI components, `web/src/api/client.ts` wrappers rather than raw `fetch`, and colocated `*.test.ts(x)` files.

## File Structure

| File | Responsibility |
|---|---|
| `web/src/setup/readiness.ts` | Pure readiness computation. No I/O, no React. |
| `web/src/setup/readiness.test.ts` | Readiness rules. |
| `web/src/setup/SetupPage.tsx` | The wizard shell and its four steps. |
| `web/src/setup/SetupPage.test.tsx` | Rendering and skip behaviour. |
| `web/src/routes.ts` | Add the `setup` route constant. |
| `web/src/App.tsx` | Mount the route and redirect while blocking steps are incomplete. |

---

### Task 1: Readiness computation

**Files:**
- Create: `web/src/setup/readiness.ts`
- Test: `web/src/setup/readiness.test.ts`

**Interfaces:**
- Consumes: `ConnectionList`, `ProfileStatus`, `ProfileAnswers`, `AgentConfig` from `web/src/api/types.ts`
- Produces:
  - `type SetupStepId = "connect" | "truth" | "identity" | "targets"`
  - `BLOCKING_STEPS: readonly SetupStepId[]`
  - `REQUIRED_IDENTITY_FIELDS: readonly (keyof ProfileAnswers)[]`
  - `interface SetupReadiness { complete: boolean; incomplete: SetupStepId[]; blocking: SetupStepId[] }`
  - `function readiness(input: ReadinessInput): SetupReadiness`
  - `interface ReadinessInput { connections: ConnectionList; profile: ProfileStatus; answers: ProfileAnswers; agent: AgentConfig }`

- [ ] **Step 1: Write the failing tests**

Create `web/src/setup/readiness.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { AgentConfig, ConnectionList, ProfileAnswers, ProfileStatus } from "../api/types";
import { readiness, type ReadinessInput } from "./readiness";

function connections(overrides: Partial<{ subscription: boolean; apiKey: boolean }> = {}): ConnectionList {
  return {
    encryptionAvailable: true,
    connections: [
      {
        provider: "claude",
        label: "Claude",
        modes: [],
        subscriptionConnected: overrides.subscription ?? true,
        apiKeyConnected: overrides.apiKey ?? false,
        authMode: "oauth",
        expiresAt: null,
        connectedAt: null,
      },
    ],
  } as ConnectionList;
}

function answers(overrides: Partial<ProfileAnswers> = {}): ProfileAnswers {
  return { name: "Ada", email: "ada@example.com", phone: "+49 30 1234", ...overrides } as ProfileAnswers;
}

function input(overrides: Partial<ReadinessInput> = {}): ReadinessInput {
  return {
    connections: connections(),
    profile: { hasProfile: true } as ProfileStatus,
    answers: answers(),
    agent: { targetCompanies: ["Grafana Labs"] } as AgentConfig,
    ...overrides,
  };
}

describe("readiness", () => {
  it("reports complete when every step is satisfied", () => {
    const result = readiness(input());
    expect(result.complete).toBe(true);
    expect(result.incomplete).toEqual([]);
    expect(result.blocking).toEqual([]);
  });

  it("treats an api key as connected, not only a subscription", () => {
    const result = readiness(
      input({ connections: connections({ subscription: false, apiKey: true }) }),
    );
    expect(result.incomplete).not.toContain("connect");
  });

  it("flags connect when neither a subscription nor a key is present", () => {
    const result = readiness(
      input({ connections: connections({ subscription: false, apiKey: false }) }),
    );
    expect(result.incomplete).toContain("connect");
    expect(result.blocking).toContain("connect");
    expect(result.complete).toBe(false);
  });

  it("flags connect when the claude connection is absent entirely", () => {
    const result = readiness(
      input({ connections: { encryptionAvailable: true, connections: [] } as ConnectionList }),
    );
    expect(result.blocking).toContain("connect");
  });

  it("flags truth when no profile has been built", () => {
    const result = readiness(input({ profile: { hasProfile: false } as ProfileStatus }));
    expect(result.incomplete).toContain("truth");
    expect(result.blocking).toContain("truth");
  });

  it("flags identity when a required field is blank", () => {
    const result = readiness(input({ answers: answers({ phone: "  " }) }));
    expect(result.incomplete).toContain("identity");
  });

  it("does not treat identity as blocking", () => {
    const result = readiness(input({ answers: answers({ phone: "" }) }));
    expect(result.blocking).not.toContain("identity");
    expect(result.complete).toBe(false);
  });

  it("flags targets when no target companies are set", () => {
    const result = readiness(input({ agent: { targetCompanies: [] } as AgentConfig }));
    expect(result.incomplete).toContain("targets");
    expect(result.blocking).not.toContain("targets");
  });

  it("lists incomplete steps in wizard order", () => {
    const result = readiness({
      connections: connections({ subscription: false, apiKey: false }),
      profile: { hasProfile: false } as ProfileStatus,
      answers: answers({ name: "" }),
      agent: { targetCompanies: [] } as AgentConfig,
    });
    expect(result.incomplete).toEqual(["connect", "truth", "identity", "targets"]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/setup/readiness.test.ts`
Expected: FAIL — cannot resolve `./readiness`.

- [ ] **Step 3: Write the implementation**

Create `web/src/setup/readiness.ts`:

```ts
import type { AgentConfig, ConnectionList, ProfileAnswers, ProfileStatus } from "../api/types";

/** The four first-run steps, in the order the wizard presents them. */
export type SetupStepId = "connect" | "truth" | "identity" | "targets";

const STEP_ORDER: readonly SetupStepId[] = ["connect", "truth", "identity", "targets"] as const;

/**
 * Steps that must be finished before the app is usable at all. The other two
 * are required only before the agent submits anything — `agent/RUNBOOK.md` §5
 * already refuses to apply with blank answers — so they stay skippable rather
 * than trapping someone who only wants to generate a CV.
 */
export const BLOCKING_STEPS: readonly SetupStepId[] = ["connect", "truth"] as const;

/** Identity fields every application form asks for; blank means step unfinished. */
export const REQUIRED_IDENTITY_FIELDS: readonly (keyof ProfileAnswers)[] = [
  "name",
  "email",
  "phone",
] as const;

export interface ReadinessInput {
  connections: ConnectionList;
  profile: ProfileStatus;
  answers: ProfileAnswers;
  agent: AgentConfig;
}

export interface SetupReadiness {
  /** True when nothing is outstanding. */
  complete: boolean;
  /** Every unfinished step, in wizard order. */
  incomplete: SetupStepId[];
  /** The subset of `incomplete` that must be finished before using the app. */
  blocking: SetupStepId[];
}

function claudeConnected(list: ConnectionList): boolean {
  const claude = list.connections.find((c) => c.provider === "claude");
  return Boolean(claude && (claude.subscriptionConnected || claude.apiKeyConnected));
}

function identityComplete(answers: ProfileAnswers): boolean {
  return REQUIRED_IDENTITY_FIELDS.every((field) => String(answers[field] ?? "").trim() !== "");
}

/**
 * Which first-run steps are outstanding.
 *
 * Pure, and computed from four endpoints the frontend already calls, so there
 * is exactly one definition of "ready" rather than one here and another on the
 * server.
 */
export function readiness(input: ReadinessInput): SetupReadiness {
  const done: Record<SetupStepId, boolean> = {
    connect: claudeConnected(input.connections),
    truth: input.profile.hasProfile,
    identity: identityComplete(input.answers),
    targets: input.agent.targetCompanies.length > 0,
  };

  const incomplete = STEP_ORDER.filter((step) => !done[step]);
  return {
    complete: incomplete.length === 0,
    incomplete,
    blocking: incomplete.filter((step) => BLOCKING_STEPS.includes(step)),
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx vitest run src/setup/readiness.test.ts`
Expected: PASS, 9 tests.

- [ ] **Step 5: Typecheck**

Run: `cd web && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add web/src/setup/readiness.ts web/src/setup/readiness.test.ts
git commit -m "Add first-run readiness computation

Pure function over the four endpoints the frontend already calls, so
there is one definition of ready rather than one here and another on
the server. connect and truth block; identity and targets are needed
only before the agent applies, so they stay skippable."
```

---

### Task 2: The setup page

**Files:**
- Create: `web/src/setup/SetupPage.tsx`
- Test: `web/src/setup/SetupPage.test.tsx`

**Interfaces:**
- Consumes: `readiness`, `SetupStepId`, `BLOCKING_STEPS` from Task 1; `listConnections`, `getProfile`, `getProfileAnswers`, `getAgentConfig` from `web/src/api/client.ts`
- Produces: `SetupPage: React.FC<{ onFinished: () => void }>`

- [ ] **Step 1: Write the failing tests**

Create `web/src/setup/SetupPage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  listConnections: vi.fn(),
  getProfile: vi.fn(),
  getProfileAnswers: vi.fn(),
  getAgentConfig: vi.fn(),
}));

import { getAgentConfig, getProfile, getProfileAnswers, listConnections } from "../api/client";
import { SetupPage } from "./SetupPage";

function connected(subscription: boolean) {
  return {
    encryptionAvailable: true,
    connections: [
      {
        provider: "claude",
        label: "Claude",
        modes: [],
        subscriptionConnected: subscription,
        apiKeyConnected: false,
        authMode: "oauth",
        expiresAt: null,
        connectedAt: null,
      },
    ],
  };
}

beforeEach(() => {
  vi.mocked(listConnections).mockResolvedValue(connected(false) as never);
  vi.mocked(getProfile).mockResolvedValue({ hasProfile: false } as never);
  vi.mocked(getProfileAnswers).mockResolvedValue({ name: "", email: "", phone: "" } as never);
  vi.mocked(getAgentConfig).mockResolvedValue({ targetCompanies: [] } as never);
});

function renderPage(onFinished = vi.fn()) {
  return render(
    <MemoryRouter>
      <SetupPage onFinished={onFinished} />
    </MemoryRouter>,
  );
}

describe("SetupPage", () => {
  it("shows all four steps", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/connect claude/i)).toBeInTheDocument());
    expect(screen.getByText(/linkedin/i)).toBeInTheDocument();
    expect(screen.getByText(/your details/i)).toBeInTheDocument();
    expect(screen.getByText(/target companies/i)).toBeInTheDocument();
  });

  it("marks a satisfied step as done", async () => {
    vi.mocked(listConnections).mockResolvedValue(connected(true) as never);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("setup-step-connect")).toHaveAttribute("data-done", "true"),
    );
    expect(screen.getByTestId("setup-step-truth")).toHaveAttribute("data-done", "false");
  });

  it("offers a skip only on non-blocking steps", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("setup-step-connect")).toBeInTheDocument());
    expect(screen.queryByTestId("setup-skip-connect")).toBeNull();
    expect(screen.queryByTestId("setup-skip-truth")).toBeNull();
    expect(screen.getByTestId("setup-skip-identity")).toBeInTheDocument();
    expect(screen.getByTestId("setup-skip-targets")).toBeInTheDocument();
  });

  it("calls onFinished once nothing is outstanding", async () => {
    vi.mocked(listConnections).mockResolvedValue(connected(true) as never);
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: true } as never);
    vi.mocked(getProfileAnswers).mockResolvedValue({
      name: "Ada",
      email: "ada@example.com",
      phone: "+49",
    } as never);
    vi.mocked(getAgentConfig).mockResolvedValue({ targetCompanies: ["Grafana"] } as never);

    const onFinished = vi.fn();
    renderPage(onFinished);

    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
  });

  it("surfaces a failed check instead of showing an empty page", async () => {
    vi.mocked(getProfile).mockRejectedValue(new Error("backend unreachable"));
    renderPage();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/backend unreachable/i));
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/setup/SetupPage.test.tsx`
Expected: FAIL — cannot resolve `./SetupPage`.

- [ ] **Step 3: Write the implementation**

Create `web/src/setup/SetupPage.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { getAgentConfig, getProfile, getProfileAnswers, listConnections } from "../api/client";
import { ROUTES, stepPath } from "../routes";
import { BLOCKING_STEPS, readiness, type SetupStepId } from "./readiness";

/** Copy and destination for each first-run step. */
const STEPS: {
  id: SetupStepId;
  title: string;
  why: string;
  action: string;
  to: string;
}[] = [
  {
    id: "connect",
    title: "Connect Claude",
    why: "TruthCV writes with Claude. Sign in with your Claude account — you do not need an API key.",
    action: "Connect",
    to: ROUTES.agents,
  },
  {
    id: "truth",
    title: "Upload your LinkedIn PDF",
    why: "This becomes your truth file — the only source of facts TruthCV is allowed to use.",
    action: "Upload",
    to: stepPath("upload"),
  },
  {
    id: "identity",
    title: "Your details",
    why: "Name, email, phone and the other questions every application form asks. Needed before TruthCV can apply for you.",
    action: "Fill in",
    to: ROUTES.agents,
  },
  {
    id: "targets",
    title: "Target companies",
    why: "Which employers TruthCV should watch. Needed only if you want it to apply on your own behalf.",
    action: "Choose",
    to: ROUTES.agents,
  },
];

/**
 * The first-run wizard.
 *
 * Readiness is recomputed from the same four endpoints every time this mounts,
 * so a step finished elsewhere in the app is reflected here without any shared
 * state to keep in sync.
 */
export function SetupPage({ onFinished }: { onFinished: () => void }) {
  const [done, setDone] = useState<Record<SetupStepId, boolean> | null>(null);
  const [skipped, setSkipped] = useState<SetupStepId[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [connections, profile, answers, agent] = await Promise.all([
        listConnections(),
        getProfile(),
        getProfileAnswers(),
        getAgentConfig(),
      ]);
      const result = readiness({ connections, profile, answers, agent });
      setDone({
        connect: !result.incomplete.includes("connect"),
        truth: !result.incomplete.includes("truth"),
        identity: !result.incomplete.includes("identity"),
        targets: !result.incomplete.includes("targets"),
      });
      setError("");
      if (result.complete) onFinished();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [onFinished]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error) {
    return (
      <Box className="shell" sx={{ p: 4 }}>
        <Alert severity="error" role="alert">
          {error}
        </Alert>
      </Box>
    );
  }

  if (!done) {
    return (
      <Box className="shell" sx={{ display: "flex", justifyContent: "center", p: 6 }}>
        <CircularProgress size={20} />
      </Box>
    );
  }

  return (
    <Box className="shell" sx={{ maxWidth: 720, mx: "auto", p: 4 }}>
      <Typography variant="h5" gutterBottom>
        Welcome to TruthCV
      </Typography>
      <Typography variant="body1" sx={{ mb: 3, color: "text.secondary" }}>
        Four things and you are set up. Everything stays on this computer.
      </Typography>

      <Stack spacing={2}>
        {STEPS.map((step) => {
          const isDone = done[step.id];
          const isSkipped = skipped.includes(step.id);
          const canSkip = !BLOCKING_STEPS.includes(step.id);
          return (
            <Box
              key={step.id}
              data-testid={`setup-step-${step.id}`}
              data-done={String(isDone)}
              sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 2 }}
            >
              <Typography variant="subtitle1">
                {isDone ? "✓ " : ""}
                {step.title}
              </Typography>
              <Typography variant="body2" sx={{ color: "text.secondary", mb: 1 }}>
                {step.why}
              </Typography>
              {!isDone && !isSkipped && (
                <Stack direction="row" spacing={1}>
                  <Button component={RouterLink} to={step.to} variant="contained" size="small">
                    {step.action}
                  </Button>
                  {canSkip && (
                    <Button
                      data-testid={`setup-skip-${step.id}`}
                      size="small"
                      onClick={() => setSkipped((prev) => [...prev, step.id])}
                    >
                      Skip for now
                    </Button>
                  )}
                </Stack>
              )}
            </Box>
          );
        })}
      </Stack>
    </Box>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx vitest run src/setup/SetupPage.test.tsx`
Expected: PASS, 5 tests.

- [ ] **Step 5: Typecheck**

Run: `cd web && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add web/src/setup/SetupPage.tsx web/src/setup/SetupPage.test.tsx
git commit -m "Add the first-run setup page

Four steps over the endpoints that already exist. Connect and truth are
required; identity and targets can be skipped, because the agent
already refuses to apply with blank answers and someone who only wants
a CV should not be trapped behind agent configuration."
```

---

### Task 3: Route and redirect

**Files:**
- Modify: `web/src/routes.ts`, `web/src/App.tsx`
- Test: `web/src/App.routes.test.tsx`

**Interfaces:**
- Consumes: `SetupPage` from Task 2, `readiness` from Task 1
- Produces: `ROUTES.setup === "/setup"`

- [ ] **Step 1: Write the failing test**

Append to `web/src/App.routes.test.tsx`:

```tsx
  it("redirects to /setup while a blocking step is outstanding", async () => {
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: false } as never);
    renderApp("/cv/upload");
    await waitFor(() => expect(screen.getByText(/welcome to truthcv/i)).toBeInTheDocument());
  });

  it("does not redirect once the blocking steps are done", async () => {
    vi.mocked(getProfile).mockResolvedValue({ hasProfile: true } as never);
    renderApp("/applications");
    await waitFor(() => expect(screen.queryByText(/welcome to truthcv/i)).toBeNull());
  });
```

Match the existing mocks and `renderApp` helper already in that file; if `getProfile` is not currently mocked there, add it to the existing `vi.mock("./api/client", …)` block alongside the mocks already present.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npx vitest run src/App.routes.test.tsx`
Expected: FAIL — no "Welcome to TruthCV" text, because nothing redirects yet.

- [ ] **Step 3: Add the route constant**

In `web/src/routes.ts`, add to the `ROUTES` object:

```ts
  setup: "/setup",
```

- [ ] **Step 4: Mount the route and the redirect**

In `web/src/App.tsx`:

Add the import beside the other page imports:

```tsx
import { SetupPage } from "./setup/SetupPage";
```

Add the route beside the other `<Route>` entries:

```tsx
<Route path={ROUTES.setup} element={<SetupPage onFinished={() => navigate(ROUTES.cv)} />} />
```

Then, in the component that already performs the startup profile check (the one showing `BootSplash`), redirect while a blocking step is outstanding. The check must run once at boot, not on every navigation, and must not fire while already on `/setup`:

```tsx
// Send a first-run user to /setup rather than dropping them into a wizard
// that cannot work yet. Only the blocking steps redirect — identity and
// targets are needed before the agent applies, not before the app is usable.
useEffect(() => {
  if (location.pathname === ROUTES.setup) return;
  let cancelled = false;
  void (async () => {
    try {
      const [connections, profile, answers, agent] = await Promise.all([
        listConnections(),
        getProfile(),
        getProfileAnswers(),
        getAgentConfig(),
      ]);
      if (cancelled) return;
      if (readiness({ connections, profile, answers, agent }).blocking.length > 0) {
        navigate(ROUTES.setup, { replace: true });
      }
    } catch {
      // A failed check must never trap someone on a blank screen; leave them
      // where they are and let the page they asked for report its own error.
    }
  })();
  return () => {
    cancelled = true;
  };
  // Boot-time only: re-running on every navigation would fire four requests
  // per click and fight the user's own navigation.
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, []);
```

Add the imports this needs:

```tsx
import { getAgentConfig, getProfileAnswers, listConnections, listPendingApprovals } from "./api/client";
import { readiness } from "./setup/readiness";
```

(`listPendingApprovals` is already imported — extend that existing import rather than adding a second one. `getProfile` may also already be imported; do not duplicate it.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npx vitest run src/App.routes.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the whole frontend suite and typecheck**

Run: `cd web && npm test && npm run typecheck`
Expected: all pass, no type errors.

- [ ] **Step 7: Verify it in the real app**

Run: `docker compose up -d --build app`

Open the app at the port in your `.env` (`grep APP_PORT .env`). Because your profile already exists, you should land on the normal wizard, **not** `/setup`. Then visit `/setup` directly and confirm all four steps render with the satisfied ones ticked.

- [ ] **Step 8: Commit**

```bash
git add web/src/routes.ts web/src/App.tsx web/src/App.routes.test.tsx
git commit -m "Route first-run users to the setup wizard

Redirects to /setup while a blocking step is outstanding, once at boot
rather than on every navigation. A failed readiness check leaves the
user where they are instead of trapping them on a blank screen."
```

---

## Self-review

**Spec coverage**

| Spec requirement | Task |
|---|---|
| Readiness from four existing routes | 1 |
| No aggregate `/api/setup-status` endpoint | 1 (Global Constraints) |
| Steps 1 and 2 required, 3 and 4 skippable | 1 (`BLOCKING_STEPS`), 2 (skip buttons) |
| Redirect to `/setup` when incomplete | 3 |
| Step 3 replaces the `answers.local.yaml` command | 2 (links to the answers UI) |
| Step 4 links to the noVNC viewport | **Gap — see below** |

**Known gap:** the spec says step 4 links to the noVNC viewport on the resolved `NOVNC_HOST_PORT`. This plan links to the Agents page instead. The frontend has no way to learn that port: it is a host-side compose value the browser never sees, and reading it would need the new backend endpoint the spec rules out. Resolving this needs a decision — expose the port through an existing settings payload, or have the setup page tell the user to find the link in `SETUP.md`. Flagged rather than guessed, because either answer changes the backend constraint.

**Placeholder scan:** none. Every step carries the code it needs.

**Type consistency:** `SetupStepId`, `BLOCKING_STEPS`, `readiness`, `ReadinessInput` and `SetupReadiness` are named identically in Task 1's definition, Task 2's consumption and Task 3's redirect.
