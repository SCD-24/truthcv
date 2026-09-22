import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormHelperText from "@mui/material/FormHelperText";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { getJevSettings, saveJevSettings, testJevKey } from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { SettingsSection } from "./SettingsModal";
import type { JevSettings } from "../api/types";

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok"; detail: string }
  | { kind: "fail"; detail: string };

/** Jev cross-check settings: an optional external cross-check used during
 * screening. It only runs when a key is saved AND the checkbox is on, so the
 * checkbox stays disabled until a key exists — flipping it can never
 * silently do nothing. */
export function JevSection() {
  const [status, setStatus] = useState<JevSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [test, setTest] = useState<TestState>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getJevSettings()
      .then((s) => alive && setStatus(s))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load Jev settings."),
      );
    return () => {
      alive = false;
    };
  }, []);

  async function handleSaveKey() {
    setSaving(true);
    setError(null);
    try {
      // An empty apiKey is a deliberate clear — the button is disabled unless
      // there's either a typed key or an existing one to clear.
      const next = await saveJevSettings({ apiKey });
      setStatus(next);
      setApiKey("");
      setTest({ kind: "idle" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the Jev key.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTest({ kind: "testing" });
    try {
      const res = await testJevKey();
      setTest(
        res.ok
          ? { kind: "ok", detail: res.detail || "Connected." }
          : { kind: "fail", detail: res.detail || "Couldn't connect." },
      );
    } catch (e) {
      setTest({
        kind: "fail",
        detail: e instanceof Error ? e.message : "Couldn't connect.",
      });
    }
  }

  async function handleToggle(checked: boolean) {
    if (!status?.keySet) return;
    setToggling(true);
    setError(null);
    try {
      const next = await saveJevSettings({ useForScreening: checked });
      setStatus(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the setting.");
    } finally {
      setToggling(false);
    }
  }

  if (!status) {
    // A failed load must surface, not spin forever: without this branch the
    // error set by the load catch above would be computed and never rendered.
    return (
      <SettingsSection
        title="Jev cross-check"
        description="An optional external cross-check TruthCV can run during screening."
      >
        {error ? (
          <Alert severity="error">{error}</Alert>
        ) : (
          <Typography color="text.secondary">Loading…</Typography>
        )}
      </SettingsSection>
    );
  }

  const canSaveKey = apiKey !== "" || status.keySet;

  return (
    <SettingsSection
      title="Jev cross-check"
      description="An optional external cross-check TruthCV can run during screening."
    >
      {error && <Alert severity="error">{error}</Alert>}
      <TextField
        label="Jev API key"
        type="password"
        autoComplete="off"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder={status.keySet ? "•••••  key saved" : "Paste your Jev API key"}
        helperText={
          status.keySet
            ? "Key saved. Leave blank and save to clear it, or type a new one to replace it."
            : "Stored encrypted on the server — never sent back to the browser."
        }
      />
      <Stack direction="row" spacing={1.5}>
        <Button variant="contained" onClick={handleSaveKey} disabled={saving || !canSaveKey}>
          {saving && <ButtonSpinner />}
          {saving ? "Saving…" : "Save key"}
        </Button>
        <Button
          variant="outlined"
          onClick={handleTest}
          disabled={!status.keySet || test.kind === "testing"}
        >
          {test.kind === "testing" && <ButtonSpinner />}
          {test.kind === "testing" ? "Testing…" : "Test key"}
        </Button>
      </Stack>
      {test.kind === "ok" && <Alert severity="success">{test.detail}</Alert>}
      {test.kind === "fail" && <Alert severity="error">{test.detail}</Alert>}
      <Box>
        <FormControlLabel
          control={
            <Checkbox
              checked={status.useForScreening}
              disabled={!status.keySet || toggling}
              onChange={(e) => handleToggle(e.target.checked)}
            />
          }
          label="Use Jev for screening"
        />
        <FormHelperText>
          {status.keySet
            ? "Jev runs during screening as an extra cross-check when this is on."
            : "Save a Jev API key first — Jev only runs when a key is saved and this is on."}
        </FormHelperText>
      </Box>
    </SettingsSection>
  );
}
