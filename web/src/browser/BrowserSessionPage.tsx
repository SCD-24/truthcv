import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, AppBar, Box, Button, Stack, Toolbar, Typography } from "@mui/material";
import RFB from "@novnc/novnc/lib/rfb";

import {
  BrowserSessionError,
  closeBrowserSession,
  getBrowserSession,
  openBrowserSession,
} from "../api/client";
import { ROUTES, browserSessionPath } from "../routes";

/** 409 refusal copy, keyed by the session server's `detail.reason`. A
 * reason vitest/the server didn't send (or one this page doesn't
 * recognize) falls back to the "agent is busy" wording below — the most
 * common case in practice, since most 409s come from a run in progress. */
const REFUSAL_COPY: Record<string, string> = {
  agent_running: "The agent is applying right now. Try again in a few minutes.",
  profile_busy: "The browser could not be started — its profile is busy. Try again shortly.",
  launch_failed: "The browser could not be started.",
  probe_failed: "The browser could not be started.",
};

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
  const [deadline, setDeadline] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const rfbRef = useRef<RFB | null>(null);

  // Open the session once on mount.
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
        if (e.status === 409) {
          setState("refused");
          if (e.reason === "session_open") {
            setMessage("A sign-in session is already open.");
            setConflictUrl(e.conflictUrl);
          } else {
            setMessage(
              (e.reason && REFUSAL_COPY[e.reason]) ||
                "The agent is applying right now. Try again in a few minutes.",
            );
          }
        } else {
          setState("unavailable");
          setMessage("The browser is unavailable.");
        }
      });
    return () => {
      live = false;
    };
  }, [url]);

  // Attach noVNC once the session is live.
  useEffect(() => {
    if (state !== "live" || !canvasRef.current || rfbRef.current) return;
    const wsUrl = `${location.origin.replace(/^http/, "ws")}/api/browser/session/stream`;
    const rfb = new RFB(canvasRef.current, wsUrl);
    rfb.addEventListener("disconnect", () => setState("closed"));
    rfbRef.current = rfb;
    return () => {
      rfb.disconnect();
      rfbRef.current = null;
    };
  }, [state]);

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

  const back = (
    <Button onClick={() => navigate(ROUTES.agents)}>Back to Agents</Button>
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
          <Button size="small" onClick={() => rfbRef.current?.disconnect()}>
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
