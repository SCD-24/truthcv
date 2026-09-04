import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import Badge from "@mui/material/Badge";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import EditNoteOutlinedIcon from "@mui/icons-material/EditNoteOutlined";
import FormatPaintOutlinedIcon from "@mui/icons-material/FormatPaintOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import InsightsOutlinedIcon from "@mui/icons-material/InsightsOutlined";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import WorkOutlineOutlinedIcon from "@mui/icons-material/WorkOutlineOutlined";
import PlaylistAddCheckOutlinedIcon from "@mui/icons-material/PlaylistAddCheckOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import TravelExploreOutlinedIcon from "@mui/icons-material/TravelExploreOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import { ROUTES } from "../routes";

interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
  dataTour: string;
}

interface Props {
  pathname: string;
  onNavigate: (path: string) => void;
  onOpenSettings: () => void;
  pendingApprovals?: number;
  signinSites?: number;
}

/**
 * The sidebar's flat set of destinations — no numbered wizard steps, just the
 * app's pages. Structure/layout stays in shell.css; the interactive marks are
 * MUI so they inherit the ledger theme.
 */
export function SideNav({
  pathname,
  onNavigate,
  onOpenSettings,
  pendingApprovals = 0,
  signinSites = 0,
}: Props) {
  const items: NavItem[] = [
    {
      path: ROUTES.uploadCv,
      label: "Upload CV",
      icon: <UploadFileOutlinedIcon fontSize="small" />,
      dataTour: "nav-upload-cv",
    },
    {
      path: ROUTES.truthFile,
      label: "Truth file",
      icon: <FactCheckOutlinedIcon fontSize="small" />,
      dataTour: "nav-truth-file",
    },
    {
      path: ROUTES.manual,
      label: "Manual",
      icon: <EditNoteOutlinedIcon fontSize="small" />,
      dataTour: "nav-manual",
    },
    {
      path: ROUTES.writingStyle,
      label: "Writing Style",
      icon: <FormatPaintOutlinedIcon fontSize="small" />,
      dataTour: "nav-writing-style",
    },
    {
      path: ROUTES.jobBoards,
      label: "Job boards",
      // Sites the agent hit a sign-in wall on and cannot get past without
      // the operator. The Site sign-ins list is empty most of the time, so
      // without this the one moment it is not is invisible until someone
      // happens to open the page. A count of sites the agent was BLOCKED on
      // is the agent's own experience — this is not, and must not become, an
      // indicator of which sites are signed in.
      icon: (
        <Badge badgeContent={signinSites} color="primary">
          <WorkOutlineOutlinedIcon fontSize="small" />
        </Badge>
      ),
      dataTour: "nav-job-boards",
    },
    {
      path: ROUTES.applications,
      label: "Applications",
      icon: <DescriptionOutlinedIcon fontSize="small" />,
      dataTour: "nav-applications",
    },
    {
      path: ROUTES.analytics,
      label: "Analytics",
      icon: <InsightsOutlinedIcon fontSize="small" />,
      dataTour: "nav-analytics",
    },
    {
      path: ROUTES.agents,
      label: "Agents",
      icon: <SmartToyOutlinedIcon fontSize="small" />,
      dataTour: "nav-agents",
    },
    {
      path: ROUTES.screenings,
      label: "Screenings",
      icon: <FactCheckOutlinedIcon fontSize="small" />,
      dataTour: "nav-screenings",
    },
    {
      path: ROUTES.companyResearch,
      label: "Company Research",
      icon: <TravelExploreOutlinedIcon fontSize="small" />,
      dataTour: "nav-company-research",
    },
    {
      path: ROUTES.approvals,
      label: "Approvals",
      icon: (
        <Badge badgeContent={pendingApprovals} color="primary">
          <PlaylistAddCheckOutlinedIcon fontSize="small" />
        </Badge>
      ),
      dataTour: "nav-approvals",
    },
  ];

  return (
    <Box component="nav" className="rail" aria-label="Destinations">
      <div className="rail__brand">
        Truth<span>CV</span>
      </div>

      <Box className="rail__bottom">
        <Typography variant="body2" className="rail__foot" sx={{ color: "text.secondary" }}>
          Every fact traces back to a source. Nothing reaches your CV unless it
          does.
        </Typography>
        {items.map((item) => {
          const active = pathname === item.path || pathname.startsWith(`${item.path}/`);
          return (
            <Button
              key={item.path}
              fullWidth
              variant={active ? "contained" : "outlined"}
              startIcon={item.icon}
              onClick={() => onNavigate(item.path)}
              aria-current={active ? "page" : undefined}
              data-tour={item.dataTour}
              sx={{ justifyContent: "flex-start" }}
            >
              {item.label}
            </Button>
          );
        })}
        <Button
          fullWidth
          variant="outlined"
          startIcon={<SettingsOutlinedIcon fontSize="small" />}
          onClick={onOpenSettings}
          data-tour="nav-settings"
          sx={{ justifyContent: "flex-start" }}
        >
          Settings
        </Button>
      </Box>
    </Box>
  );
}
