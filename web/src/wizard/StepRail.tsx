import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import InsightsOutlinedIcon from "@mui/icons-material/InsightsOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { STEPS, stepIndex, type StepId } from "./steps";

interface Props {
  current: StepId;
  reached: StepId;
  onNavigate: (to: StepId) => void;
  onOpenSettings: () => void;
  onOpenApplications: () => void;
  onOpenAnalytics: () => void;
  /** True when the applications page (not the wizard) is the active view. */
  applicationsActive?: boolean;
  /** True when the analytics page (not the wizard) is the active view. */
  analyticsActive?: boolean;
}

/**
 * The step rail — the wizard presented as an auditable record of progress.
 * Structure/layout stays in shell.css (a CSS-grid sidebar the theme can't
 * express); the interactive marks are MUI so they inherit the ledger theme.
 */
export function StepRail({
  current,
  reached,
  onNavigate,
  onOpenSettings,
  onOpenApplications,
  onOpenAnalytics,
  applicationsActive = false,
  analyticsActive = false,
}: Props) {
  const reachedIdx = stepIndex(reached);
  const currentIdx = stepIndex(current);

  return (
    <Box component="nav" className="rail" aria-label="Wizard steps">
      <div className="rail__brand">
        Truth<span>CV</span>
      </div>

      <Box component="ol" className="rail__steps">
        {STEPS.map((step, i) => {
          const state =
            i === currentIdx ? "current" : i < reachedIdx ? "done" : "upcoming";
          const reachable = i <= reachedIdx;
          return (
            <li key={step.id}>
              <button
                type="button"
                className="rail__step"
                data-state={state}
                disabled={!reachable}
                aria-current={state === "current" ? "step" : undefined}
                onClick={() => reachable && onNavigate(step.id)}
              >
                <span className="rail__marker" aria-hidden="true">
                  {state === "done" ? "✓" : i + 1}
                </span>
                <span className="rail__label">{step.label}</span>
              </button>
            </li>
          );
        })}
      </Box>

      <Box className="rail__bottom">
        <Typography variant="body2" className="rail__foot" sx={{ color: "text.secondary" }}>
          Every fact traces back to a source. Nothing reaches your CV unless it
          does.
        </Typography>
        <Button
          fullWidth
          variant={applicationsActive ? "contained" : "outlined"}
          startIcon={<DescriptionOutlinedIcon fontSize="small" />}
          onClick={onOpenApplications}
          aria-current={applicationsActive ? "page" : undefined}
          sx={{ justifyContent: "flex-start" }}
        >
          Applications
        </Button>
        <Button
          fullWidth
          variant={analyticsActive ? "contained" : "outlined"}
          startIcon={<InsightsOutlinedIcon fontSize="small" />}
          onClick={onOpenAnalytics}
          aria-current={analyticsActive ? "page" : undefined}
          sx={{ justifyContent: "flex-start" }}
        >
          Analytics
        </Button>
        <Button
          fullWidth
          variant="outlined"
          startIcon={<SettingsOutlinedIcon fontSize="small" />}
          onClick={onOpenSettings}
          sx={{ justifyContent: "flex-start" }}
        >
          Settings
        </Button>
      </Box>
    </Box>
  );
}
