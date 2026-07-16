import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import type { StepProps } from "../wizard/steps";
import { useWizard } from "../wizard/store";
import { tailor } from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import "../styles/step.css";

export function PostingStep({ onAdvance, onBack }: StepProps) {
  const { posting, setPosting, setTailor, run, loading, error } = useWizard();

  const submit = async () => {
    if (!posting.trim()) return;
    const result = await run(() => tailor(posting.trim()));
    if (result) {
      setTailor(result);
      onAdvance("confirm");
    }
  };

  return (
    <section>
      <div className="stage__head">
        <Typography variant="overline" className="eyebrow">
          Step 3 of 5
        </Typography>
        <h1 className="stage__title">Paste the job you&apos;re after</h1>
        <p className="stage__lede">
          Paste the full posting below. We tailor your CV to it using only the
          facts in your truth file.
        </p>
      </div>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      <TextField
        id="posting-text"
        label="Job posting"
        placeholder="Paste the full job description here…"
        value={posting}
        onChange={(e) => setPosting(e.target.value)}
        multiline
        minRows={10}
        fullWidth
      />

      <Box className="stage__actions" sx={{ display: "flex", gap: 2, mt: 3 }}>
        <Button variant="outlined" onClick={() => onBack("review")}>
          Back
        </Button>
        <Button
          variant="contained"
          disabled={!posting.trim() || loading}
          onClick={submit}
        >
          {loading && <ButtonSpinner />}
          {loading ? "Tailoring…" : "Tailor my CV"}
        </Button>
      </Box>
    </section>
  );
}
