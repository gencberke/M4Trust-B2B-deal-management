import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { EntityProvider } from "./entities/EntityContext";
import { DemoProvider } from "./demo/DemoContext";
import "./index.css";
import { AppRoutes } from "./routes/AppRoutes";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <DemoProvider>
          <EntityProvider><AppRoutes /></EntityProvider>
        </DemoProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
