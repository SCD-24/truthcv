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
import MarkEmailReadOutlinedIcon from "@mui/icons-material/MarkEmailReadOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import FilterAltOutlinedIcon from "@mui/icons-material/FilterAltOutlined";
import AltRouteOutlinedIcon from "@mui/icons-material/AltRouteOutlined";
import { ROUTES } from "../routes";

interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
  dataTour: string;
}

interface NavGroupData {
  id: string;
  label: string;
  items: NavItem[];
}

interface Props {
  pathname: string;
  onNavigate: (path: string) => void;
  onOpenSettings: () => void;
  pendingApprovals?: number;
  signinSites?: number;
}

interface NavGroupProps {
  group: NavGroupData;
  pathname: string;
  onNavigate: (path: string) => void;
}

const BUTTON_SX = { justifyContent: "flex-start" } as const;

/** Shorthand for one destination entry. */
function navItem(path: string, label: string, icon: React.ReactNode, dataTour: string): NavItem {
  return { path, label, icon, dataTour };
}

const PROFILE_GROUP: NavGroupData = {
  id: "profile",
  label: "Your profile",
  items: [
    navItem(ROUTES.uploadCv, "Upload CV", <UploadFileOutlinedIcon fontSize="small" />, "nav-upload-cv"),
    navItem(ROUTES.truthFile, "Truth file", <FactCheckOutlinedIcon fontSize="small" />, "nav-truth-file"),
    navItem(ROUTES.manual, "Manual", <EditNoteOutlinedIcon fontSize="small" />, "nav-manual"),
    navItem(ROUTES.writingStyle, "Writing Style", <FormatPaintOutlinedIcon fontSize="small" />, "nav-writing-style"),
  ],
};

const AUTOMATION_GROUP: NavGroupData = {
  id: "automation",
  label: "Automation",
  items: [
    navItem(ROUTES.agents, "Agents", <SmartToyOutlinedIcon fontSize="small" />, "nav-agents"),
    navItem(ROUTES.modelRouting, "Model routing", <AltRouteOutlinedIcon fontSize="small" />, "nav-model-routing"),
  ],
};

/** "Find jobs" group; the Job boards icon carries the blocked-sign-in count. */
function findJobsGroup(signinSites: number): NavGroupData {
  // Sites the agent hit a sign-in wall on and cannot get past without
  // the operator. The Site sign-ins list is empty most of the time, so
  // without this the one moment it is not is invisible until someone
  // happens to open the page. A count of sites the agent was BLOCKED on
  // is the agent's own experience — this is not, and must not become, an
  // indicator of which sites are signed in.
  const jobBoardsIcon = (
    <Badge badgeContent={signinSites} color="primary">
      <WorkOutlineOutlinedIcon fontSize="small" />
    </Badge>
  );
  return {
    id: "find-jobs",
    label: "Find jobs",
    items: [
      navItem(ROUTES.jobBoards, "Job boards", jobBoardsIcon, "nav-job-boards"),
      navItem(ROUTES.screenings, "Screenings", <FilterAltOutlinedIcon fontSize="small" />, "nav-screenings"),
      navItem(ROUTES.companyResearch, "Company Research", <TravelExploreOutlinedIcon fontSize="small" />, "nav-company-research"),
    ],
  };
}

/** "Applications" group; the Approvals icon carries the pending count. */
function applicationsGroup(pendingApprovals: number): NavGroupData {
  const approvalsIcon = (
    <Badge badgeContent={pendingApprovals} color="primary">
      <PlaylistAddCheckOutlinedIcon fontSize="small" />
    </Badge>
  );
  return {
    id: "applications",
    label: "Applications",
    items: [
      navItem(ROUTES.approvals, "Approvals", approvalsIcon, "nav-approvals"),
      navItem(ROUTES.applications, "Applications", <DescriptionOutlinedIcon fontSize="small" />, "nav-applications"),
      navItem(ROUTES.emailResponses, "Email responses", <MarkEmailReadOutlinedIcon fontSize="small" />, "nav-email-responses"),
      navItem(ROUTES.analytics, "Analytics", <InsightsOutlinedIcon fontSize="small" />, "nav-analytics"),
    ],
  };
}

/** Builds the ordered, grouped destination list (badge counts feed the icons). */
function buildGroups(pendingApprovals: number, signinSites: number): NavGroupData[] {
  return [PROFILE_GROUP, findJobsGroup(signinSites), applicationsGroup(pendingApprovals), AUTOMATION_GROUP];
}

/** One destination button; highlights when the current path is at or under it. */
function NavButton({ item, pathname, onNavigate }: Omit<NavGroupProps, "group"> & { item: NavItem }) {
  const active = pathname === item.path || pathname.startsWith(`${item.path}/`);
  return (
    <Button
      fullWidth
      variant={active ? "contained" : "outlined"}
      startIcon={item.icon}
      onClick={() => onNavigate(item.path)}
      aria-current={active ? "page" : undefined}
      data-tour={item.dataTour}
      sx={BUTTON_SX}
    >
      {item.label}
    </Button>
  );
}

/** A labelled section of related destinations. */
function NavGroup({ group, pathname, onNavigate }: NavGroupProps) {
  const labelId = `nav-group-${group.id}`;
  return (
    <Box component="section" aria-labelledby={labelId} className="rail__group">
      <Typography component="p" variant="overline" className="rail__group-label" id={labelId} sx={{ color: "text.secondary" }}>
        {group.label}
      </Typography>
      {group.items.map((item) => (
        <NavButton key={item.path} item={item} pathname={pathname} onNavigate={onNavigate} />
      ))}
    </Box>
  );
}

/**
 * The sidebar's destinations in labelled groups (Your profile, Find jobs,
 * Applications, Automation) — no numbered wizard steps, just the app's pages,
 * with Settings docked last. Structure/layout stays in shell.css; the
 * interactive marks are MUI so they inherit the ledger theme.
 */
export function SideNav({ pathname, onNavigate, onOpenSettings, pendingApprovals = 0, signinSites = 0 }: Props) {
  return (
    <Box component="nav" className="rail" aria-label="Destinations">
      <div className="rail__brand">
        Truth<span>CV</span>
      </div>
      <Box className="rail__bottom">
        <Typography variant="body2" className="rail__foot" sx={{ color: "text.secondary" }}>
          Every fact traces back to a source. Nothing reaches your CV unless it does.
        </Typography>
        {buildGroups(pendingApprovals, signinSites).map((group) => (
          <NavGroup key={group.id} group={group} pathname={pathname} onNavigate={onNavigate} />
        ))}
        <Button fullWidth variant="outlined" startIcon={<SettingsOutlinedIcon fontSize="small" />} onClick={onOpenSettings} data-tour="nav-settings" sx={BUTTON_SX}>
          Settings
        </Button>
      </Box>
    </Box>
  );
}
