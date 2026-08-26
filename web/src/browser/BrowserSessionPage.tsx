import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, AppBar, Box, Button, Stack, Toolbar, Typography } from "@mui/material";
// `@novnc/novnc` is pinned to an EXACT 1.6.0 in package.json (no caret) —
// 1.7.0's package.json restricts `exports` to `./core/rfb.js` only, which
// breaks this `lib/rfb` subpath entirely (Vite's resolver fails before this
// module even loads). Do not loosen the pin or bump the version without
// re-checking that `@novnc/novnc/lib/rfb` still resolves.
import RFB from "@novnc/novnc/lib/rfb";

import {
  BrowserSessionError,
  closeBrowserSession,
  getBrowserSession,
  openBrowserSession,
} from "../api/client";
import { ROUTES, browserSessionPath } from "../routes";

/** Refusal copy, keyed by the session server's `detail.reason`. Covers every
 * reason `REFUSAL_STATUS` in browser/session-server.js can send, across all
 * of the statuses they arrive with — this map is consulted whatever the
 * status is, so a 500 (`launch_failed`) or a 503 (`probe_failed`,
 * `agent_unreachable`) gets its own words rather than the generic "the
 * browser is unavailable". A reason the server didn't send, or one this page
 * doesn't recognize, falls back per status below. */
const REFUSAL_COPY: Record<string, string> = {
  agent_running: "The agent is applying right now. Try again in a few minutes.",
  profile_busy: "The browser could not be started — its profile is busy. Try again shortly.",
  cancelled: "The browser was not started — the session was taken. Try again.",
  bad_url: "That is not an address the browser can open.",
  launch_failed: "The browser could not be started.",
  probe_failed:
    "The browser could not be started — it could not tell whether the profile was free.",
  agent_unreachable:
    "The agent could not be reached, so the browser was not started. Try again shortly.",
};

/** How long to wait for a session the operator asked to close to actually go
 * away, before retrying the open. `close()` answers `{closing:true}` and waits
 * for the browser to exit (SIGKILL at 10s), so an immediate retry would just
 * be refused again. */
const CLOSE_WAIT_MS = 15000;
const CLOSE_POLL_MS = 500;

type State = "starting" | "live" | "refused" | "unavailable" | "closed";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** Seconds remaining until an eviction deadline, floored at zero. */
function secondsLeft(deadline: string): number {
  const ms = Date.parse(deadline) - Date.now();
  return ms > 0 ? Math.ceil(ms / 1000) : 0;
}

function mmss(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** The attended sign-in viewport.
 *
 * The noVNC socket is same-origin (`/api/browser/session/stream`) and the
 * server rejects any other Origin — the browser container's own port is not
 * published, so this is the only route to it. */
export function BrowserSessionPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const url = params.get("url") || "";
  const [state, setState] = useState<State>("starting");
  const [message, setMessage] = useState("");
  const [conflictUrl, setConflictUrl] = useState<string | null>(null);
  // Bumped to re-run the open effect after the operator closes a session that
  // was in the way. `url` alone cannot do it: the retry is at the same URL.
  const [attempt, setAttempt] = useState(0);
  const [deadline, setDeadline] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const rfbRef = useRef<RFB | null>(null);
  // Set just before a Reload-initiated disconnect, so the disconnect
  // listener below can tell "operator hit Reload" apart from "the server
  // actually closed the session" — only the latter should end the page.
  const reloadingRef = useRef(false);

  // Open the session on mount, and again on every retry (`attempt`).
  useEffect(() => {
    let live = true;
    openBrowserSession(url)
      .then((s) => {
        if (!live) return;
        setState("live");
        setDeadline(s.evictDeadline);
      })
      .catch((e: BrowserSessionError) => {
        if (!live) return;
        if (e.status === 409 && e.reason === "session_open" && e.conflictUrl === url) {
          // The session the operator is asking for is the one already open —
          // they left this page without pressing Done and came back. That is
          // not a refusal to show them: attach the viewport to it. Treating it
          // as one strands them, because the only offered way out was a button
          // that navigates to the page they are already on.
          setState("live");
          getBrowserSession()
            .then((open) => {
              if (live) setDeadline(open.evictDeadline);
            })
            .catch(() => {
              // The 5s poll below re-reads the deadline; nothing to say here.
            });
          return;
        }
        if (e.status === 409 && e.reason === "session_open") {
          setState("refused");
          setMessage(`A sign-in session is already open at ${hostOf(e.conflictUrl || "")}.`);
          setConflictUrl(e.conflictUrl);
          return;
        }
        setState(e.status === 409 ? "refused" : "unavailable");
        setMessage(
          (e.reason && REFUSAL_COPY[e.reason]) ||
            (e.status === 409
              ? "The agent is applying right now. Try again in a few minutes."
              : "The browser is unavailable."),
        );
      });
    return () => {
      live = false;
    };
  }, [url, attempt]);

  // Build a fresh RFB against the viewer socket. Used both to attach on
  // first live render and to re-attach on Reload — Reload re-makes only
  // this viewer connection, never the session server's session.
  function connect() {
    if (!canvasRef.current) return;
    const wsUrl = `${location.origin.replace(/^http/, "ws")}/api/browser/session/stream`;
    const rfb = new RFB(canvasRef.current, wsUrl);
    // noVNC 1.6.0 defaults to rendering the full remote 1920x1080 desktop
    // at native size, which overflows this page's <Box> with no way to pan
    // to the right/bottom of the desktop. Scale-and-clip it to the box instead.
    rfb.clipViewport = true;
    rfb.scaleViewport = true;
    rfb.addEventListener("disconnect", () => {
      if (reloadingRef.current) {
        // This disconnect was Reload tearing down the old socket on its way
        // to a new one, not the session actually ending — swallow it.
        reloadingRef.current = false;
        return;
      }
      setState("closed");
    });
    // A failed handshake (bad Origin, relay rejection, etc.) previously
    // looked identical to a normal close — the operator saw "Closed" for a
    // session that never actually connected. Surface it distinctly.
    rfb.addEventListener("securityfailure", (e: CustomEvent<{ reason?: string }>) => {
      setState("unavailable");
      setMessage(e.detail?.reason || "The viewport could not connect to the browser.");
    });
    rfbRef.current = rfb;
  }

  // Attach noVNC once the session is live.
  useEffect(() => {
    if (state !== "live" || rfbRef.current) return;
    connect();
    return () => {
      rfbRef.current?.disconnect();
      rfbRef.current = null;
    };
  }, [state]);

  function onReload() {
    if (!rfbRef.current) return;
    reloadingRef.current = true;
    rfbRef.current.disconnect();
    rfbRef.current = null;
    connect();
  }

  // Poll for an eviction the run may have requested.
  useEffect(() => {
    if (state !== "live") return;
    const id = setInterval(() => {
      getBrowserSession()
        .then((s) => {
          if (!s.open) setState("closed");
          else setDeadline(s.evictDeadline);
        })
        .catch(() => setState("unavailable"));
    }, 5000);
    return () => clearInterval(id);
  }, [state]);

  // Tick the countdown once a deadline exists.
  useEffect(() => {
    if (!deadline) {
      setRemaining(0);
      return;
    }
    setRemaining(secondsLeft(deadline));
    const id = setInterval(() => setRemaining(secondsLeft(deadline)), 1000);
    return () => clearInterval(id);
  }, [deadline]);

  async function onDone() {
    try {
      await closeBrowserSession();
    } catch {
      // The session is going away either way; the operator does not need to
      // hear about a failure to close something they are finished with.
    }
    setState("closed");
  }

  /** Close the session that is in the way, then open this one. The refusal
   * screen's other way out ("Go to the open session") keeps the other site's
   * session; this one gives it up. Without either, a session opened for
   * another site and forgotten locks the operator out until a scheduled run
   * evicts it — which can be hours. */
  async function onCloseAndStart() {
    setState("starting");
    setMessage("");
    setConflictUrl(null);
    try {
      await closeBrowserSession();
    } catch {
      // Nothing useful to say: the retry below reports what actually happens.
    }
    // The server answers the close before the browser has exited, so wait for
    // the slot to actually be free rather than racing straight into the same
    // refusal. Bounded: a stuck session still lands back on a screen with a
    // working button rather than spinning forever.
    const until = Date.now() + CLOSE_WAIT_MS;
    while (Date.now() < until) {
      try {
        const open = await getBrowserSession();
        if (!open.open) break;
      } catch {
        break; // The retry will surface whatever is wrong.
      }
      await new Promise((resolve) => setTimeout(resolve, CLOSE_POLL_MS));
    }
    setAttempt((n) => n + 1);
  }

  const back = (
    <Button onClick={() => navigate(ROUTES.jobBoards)}>Back to job boards</Button>
  );

  if (state === "starting") {
    return (
      <Stack spacing={2} sx={{ p: 3 }}>
        <Typography>Starting the browser…</Typography>
      </Stack>
    );
  }

  if (state === "refused" || state === "unavailable") {
    return (
      <Stack spacing={2} sx={{ p: 3 }}>
        <Alert severity={state === "refused" ? "info" : "error"}>{message}</Alert>
        {conflictUrl && (
          <Button
            variant="contained"
            onClick={() => navigate(browserSessionPath(conflictUrl))}
          >
            Go to the open session
          </Button>
        )}
        {conflictUrl && (
          <Button variant="outlined" onClick={onCloseAndStart}>
            Close it and start here
          </Button>
        )}
        {back}
      </Stack>
    );
  }

  if (state === "closed") {
    return (
      <Stack spacing={2} sx={{ p: 3 }}>
        {/* Deliberately not a success message. Nothing here checks whether the
            sign-in worked — only the next run finds out. */}
        <Typography>
          Closed. If it worked, the next run will get through; if not, this site
          will show up here again.
        </Typography>
        {back}
      </Stack>
    );
  }

  return (
    <Stack sx={{ height: "100%" }}>
      <AppBar position="static" color="default" elevation={0}>
        <Toolbar sx={{ gap: 2 }}>
          <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
            {hostOf(url)}
          </Typography>
          <Button size="small" onClick={onReload}>
            Reload
          </Button>
          <Button size="small" variant="contained" onClick={onDone}>
            Done
          </Button>
        </Toolbar>
      </AppBar>
      {deadline && (
        <Alert severity="warning">
          The agent needs the browser in {mmss(remaining)} — finish up.
        </Alert>
      )}
      <Box ref={canvasRef} sx={{ flexGrow: 1, minHeight: 480, bgcolor: "black" }} />
    </Stack>
  );
}
