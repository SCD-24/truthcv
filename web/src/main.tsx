import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Self-hosted type — the record voice. Display / body / mono roles.
import "@fontsource/schibsted-grotesk/500.css";
import "@fontsource/schibsted-grotesk/600.css";
import "@fontsource/schibsted-grotesk/700.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import { ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import "./styles/global.css";
import { App } from "./App";
import { WizardProvider } from "./wizard/store";
import { theme } from "./theme";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Missing #root element");

createRoot(rootEl).render(
  <StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <WizardProvider>
        <App />
      </WizardProvider>
    </ThemeProvider>
  </StrictMode>,
);
