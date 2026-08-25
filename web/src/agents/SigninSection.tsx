import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Divider, Paper, Stack, Typography } from "@mui/material";

import { getSigninQueue } from "../api/client";
import type { SigninQueueSite } from "../api/types";
import { browserSessionPath } from "../routes";

/** Sign-in landing pages for the platforms agentconfig/dorks.py can target.
 * Kept in step with SOURCE_DOMAINS there — a source missing here simply gets
 * no proactive row, which is a gap in convenience, never in correctness. */
const SOURCE_SIGNIN_URLS: Record<string, string> = {
  linkedin: "https://www.linkedin.com/login",
  ashby: "https://jobs.ashbyhq.com",
  greenhouse: "https://job-boards.greenhouse.io",
  lever: "https://jobs.lever.co",
  personio: "https://jobs.personio.de",
  workday: "https://www.myworkdayjobs.com",
};

function hostLabel(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Sites needing a manual sign-in: the ones the agent was actually blocked by,
 * and the boards this operator's profiles target.
 *
 * There is deliberately no signed-in indicator. The agent's experience is the
 * only source of truth, so a tick here would be an assertion nothing checks —
 * and a stale one would send the operator looking in the wrong place. */
export function SigninSection({ sources }: { sources: string[] }) {
  const navigate = useNavigate();
  const [sites, setSites] = useState<SigninQueueSite[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    getSigninQueue()
      .then((q) => live && setSites(q.sites))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, []);

  const boards = sources.filter((s) => SOURCE_SIGNIN_URLS[s]);

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack spacing={2}>
        <Stack spacing={0.5}>
          <Typography variant="h6">Site sign-ins</Typography>
          <Typography variant="body2" color="text.secondary">
            Some job sites need you to sign in once. The session is saved and
            reused by every later run.
          </Typography>
        </Stack>

        {error && <Alert severity="error">{error}</Alert>}

        <Typography variant="subtitle2">Needs attention</Typography>
        {sites && sites.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No sites are waiting on a sign-in.
          </Typography>
        )}
        {sites?.map((site) => (
          <Stack
            key={site.host}
            direction="row"
            spacing={2}
            sx={{ alignItems: "center", justifyContent: "space-between" }}
          >
            <Stack spacing={0.25}>
              <Typography variant="body2">{site.host}</Typography>
              <Typography variant="caption" color="text.secondary">
                {site.waiting} {site.waiting === 1 ? "posting" : "postings"} waiting
                {site.companies.length > 0 && ` · ${site.companies.join(", ")}`}
                {hostLabel(site.lastBlockedAt) && ` · last blocked ${hostLabel(site.lastBlockedAt)}`}
              </Typography>
            </Stack>
            <Button
              variant="contained"
              size="small"
              onClick={() => navigate(browserSessionPath(site.signinUrl))}
            >
              Sign in to {site.host}
            </Button>
          </Stack>
        ))}

        <Divider />

        <Typography variant="subtitle2">Your job boards</Typography>
        <Typography variant="body2" color="text.secondary">
          Sign in ahead of time if you like. There is no status here — TruthCV
          only learns a site needs a sign-in when the agent is actually blocked
          by one.
        </Typography>
        {boards.map((source) => (
          <Stack
            key={source}
            direction="row"
            spacing={2}
            sx={{ alignItems: "center", justifyContent: "space-between" }}
          >
            <Typography variant="body2">{source}</Typography>
            <Button
              variant="outlined"
              size="small"
              onClick={() => navigate(browserSessionPath(SOURCE_SIGNIN_URLS[source]))}
            >
              Sign in to {source}
            </Button>
          </Stack>
        ))}
      </Stack>
    </Paper>
  );
}
