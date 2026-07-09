import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/global.css";
import { App } from "./App";
import { WizardProvider } from "./wizard/store";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Missing #root element");

createRoot(rootEl).render(
  <StrictMode>
    <WizardProvider>
      <App />
    </WizardProvider>
  </StrictMode>,
);
