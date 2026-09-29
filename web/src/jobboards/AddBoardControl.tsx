import { useState } from "react";
import { Button, MenuItem, Select, Stack, TextField } from "@mui/material";

import type { JobBoard } from "../api/types";
import { BOARD_LABELS } from "./boardLabels";

// Known board keys offered by the "add a board" control. This carries no
// sign-in URLs or domains — those are resolved server-side per board — it
// only lists the catalog keys a user can pick instead of typing a domain.
const KNOWN_BOARDS = [
  "ashby",
  "greenhouse",
  "lever",
  "personio",
  "linkedin",
  "workday",
  "remoterocketship",
];

export function AddBoardControl({ onAdd, existing }: { onAdd: (board: JobBoard) => void; existing: Set<string> }) {
  const [choice, setChoice] = useState("");
  const [customDomain, setCustomDomain] = useState("");
  const [customSigninUrl, setCustomSigninUrl] = useState("");
  const [customSearchUrl, setCustomSearchUrl] = useState("");
  const [customPostingUrlPattern, setCustomPostingUrlPattern] = useState("");
  const [patternError, setPatternError] = useState("");

  function handleAdd() {
    if (choice === "__custom__") {
      if (!customDomain.trim()) return;
      const pattern = customPostingUrlPattern.trim();
      if (pattern && !/^https?:\/\//.test(pattern)) {
        setPatternError("Must start with http:// or https://");
        return;
      }
      setPatternError("");
      onAdd({
        source: customDomain.trim(),
        signinUrl: customSigninUrl.trim(),
        enabled: true,
        mode: "direct",
        modeLocked: false,
        domain: customDomain.trim(),
        effectiveSigninUrl: customSigninUrl.trim(),
        isDefault: false,
        isApi: false,
        keyRequired: false,
        searchUrl: customSearchUrl.trim(),
        postingUrlPattern: pattern,
      });
      setCustomDomain("");
      setCustomSigninUrl("");
      setCustomSearchUrl("");
      setCustomPostingUrlPattern("");
    } else if (choice) {
      // The response-only fields are placeholders here: the PUT strips them
      // and the GET that follows carries the server's resolved values, which
      // is where isApi/isDefault actually come from.
      onAdd({
        source: choice,
        signinUrl: "",
        enabled: true,
        mode: "dork",
        modeLocked: true,
        domain: "",
        effectiveSigninUrl: "",
        isDefault: false,
        isApi: false,
        keyRequired: false,
        searchUrl: "",
        postingUrlPattern: "",
      });
    }
    setChoice("");
  }

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <Select
          size="small"
          displayEmpty
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          sx={{ minWidth: 200 }}
        >
          <MenuItem value="">
            <em>Add a board…</em>
          </MenuItem>
          {KNOWN_BOARDS.filter((source) => !existing.has(source)).map((source) => (
            <MenuItem key={source} value={source}>
              {BOARD_LABELS[source] ?? source}
            </MenuItem>
          ))}
          <MenuItem value="__custom__">Custom domain…</MenuItem>
        </Select>
        <Button size="small" variant="outlined" disabled={!choice} onClick={handleAdd}>
          Add
        </Button>
      </Stack>
      {choice === "__custom__" && (
        <Stack direction="row" spacing={1}>
          <TextField
            size="small"
            label="Domain"
            value={customDomain}
            onChange={(e) => setCustomDomain(e.target.value)}
          />
          <TextField
            size="small"
            label="Sign-in URL (optional)"
            value={customSigninUrl}
            onChange={(e) => setCustomSigninUrl(e.target.value)}
          />
          <TextField
            size="small"
            label="Search URL template (optional)"
            value={customSearchUrl}
            onChange={(e) => setCustomSearchUrl(e.target.value)}
            helperText="e.g. https://www.adzuna.de/search?q={keywords}&w={location} — {keywords} required, {location} optional"
            sx={{ minWidth: 320 }}
          />
          <TextField
            size="small"
            label="Posting link pattern (optional)"
            value={customPostingUrlPattern}
            onChange={(e) => setCustomPostingUrlPattern(e.target.value)}
            error={!!patternError}
            helperText={patternError || "e.g. https://www.example.com/jobs/*"}
            sx={{ minWidth: 320 }}
          />
        </Stack>
      )}
    </Stack>
  );
}
