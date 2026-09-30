import { useState } from "react";
import type { FormEvent } from "react";
import {
  Alert,
  Autocomplete,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
} from "@mui/material";

import { CLAIM_TYPES } from "../api/types";
import type { ClaimType, CompanyFinding } from "../api/types";
import { SOURCE_CLASSES, sourceClassLabel } from "./companyresearch.logic";

/** The payload the dialog hands to its caller. */
export interface FindingDraft {
  company: string;
  claim: ClaimType;
  claimLabel?: string;
  supersedes?: string;
  value: string;
  sourceUrl: string;
  sourceClass: string;
  asOf?: string;
  note?: string;
}

/** Add-a-finding dialog. With a `finding` it becomes "Correct finding": the
 * fields are prefilled, company and claim type (and label) are locked, and the
 * submit supersedes that finding — findings are never edited in place. A
 * rejection from `onSubmit` is shown inline and the dialog stays open. */
export function FindingDialog({
  finding,
  companies,
  onClose,
  onSubmit,
}: {
  finding?: CompanyFinding;
  companies: string[];
  onClose: () => void;
  onSubmit: (draft: FindingDraft) => Promise<void>;
}) {
  const editing = finding !== undefined;
  const [company, setCompany] = useState(finding?.company ?? "");
  const [claim, setClaim] = useState<string>(finding?.claim ?? CLAIM_TYPES[0].value);
  const [claimLabel, setClaimLabel] = useState(finding?.claimLabel ?? "");
  const [value, setValue] = useState(finding?.value ?? "");
  const [sourceUrl, setSourceUrl] = useState(finding?.sourceUrl ?? "");
  const [sourceClass, setSourceClass] = useState<string>(
    finding?.sourceClass || SOURCE_CLASSES[0],
  );
  const [asOf, setAsOf] = useState(finding?.asOf ?? "");
  const [note, setNote] = useState(finding?.note ?? "");
  const [urlError, setUrlError] = useState("");
  const [labelError, setLabelError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isOther = claim === "other";
  const knownClaim = CLAIM_TYPES.some((t) => t.value === claim);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const url = sourceUrl.trim();
    const label = claimLabel.trim();
    const nextUrlError = !url
      ? "Required — every finding must cite where it came from."
      : !url.includes("://")
        ? "Must be a full link, e.g. https://example.com/page"
        : "";
    const nextLabelError = isOther && !label ? "A label is required for “Other”." : "";
    setUrlError(nextUrlError);
    setLabelError(nextLabelError);
    if (nextUrlError || nextLabelError) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit({
        company: company.trim(),
        claim: claim as ClaimType,
        claimLabel: isOther ? label : undefined,
        supersedes: finding?.id,
        value,
        sourceUrl: url,
        sourceClass,
        asOf: asOf.trim() || undefined,
        note: note || undefined,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't record the finding.");
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      slotProps={{ paper: { component: "form", onSubmit: submit } }}
    >
      <DialogTitle>{editing ? "Correct finding" : "Add finding"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && (
            <Alert severity="error" role="alert">
              {error}
            </Alert>
          )}
          <Autocomplete
            freeSolo
            disabled={editing}
            options={companies}
            inputValue={company}
            onInputChange={(_e, next) => setCompany(next)}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Company"
                size="small"
                autoFocus={!editing}
                slotProps={{
                  ...params.slotProps,
                  htmlInput: { ...params.slotProps.htmlInput, "aria-required": "true" },
                }}
              />
            )}
          />
          <TextField
            select
            label="Claim type"
            size="small"
            value={claim}
            disabled={editing}
            onChange={(e) => setClaim(e.target.value)}
            slotProps={{ select: { native: true } }}
          >
            {!knownClaim && <option value={claim}>{claim}</option>}
            {CLAIM_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </TextField>
          {isOther && (
            <TextField
              label="Claim label"
              size="small"
              value={claimLabel}
              disabled={editing}
              onChange={(e) => setClaimLabel(e.target.value)}
              error={!!labelError}
              slotProps={{
                htmlInput: { "aria-required": "true" },
                formHelperText: labelError ? { role: "alert" } : undefined,
              }}
              helperText={labelError || "What this finding is about, e.g. Headcount."}
            />
          )}
          <TextField
            label="Value"
            size="small"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            slotProps={{ htmlInput: { "aria-required": "true" } }}
          />
          <TextField
            label="Source URL"
            size="small"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://..."
            error={!!urlError}
            slotProps={{
              htmlInput: { "aria-required": "true" },
              formHelperText: urlError ? { role: "alert" } : undefined,
            }}
            helperText={urlError || "Required — every finding must cite where it came from."}
          />
          <TextField
            select
            label="Source class"
            size="small"
            value={sourceClass}
            onChange={(e) => setSourceClass(e.target.value)}
            slotProps={{ select: { native: true } }}
          >
            {SOURCE_CLASSES.map((cls) => (
              <option key={cls} value={cls}>
                {sourceClassLabel(cls)}
              </option>
            ))}
          </TextField>
          <TextField
            label="As-of date"
            size="small"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            placeholder="YYYY-MM-DD"
            helperText="Leave empty when unknown — do not guess."
          />
          <TextField
            label="Note"
            size="small"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            multiline
            minRows={2}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={busy}>
          {editing ? "Save correction" : "Add finding"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
