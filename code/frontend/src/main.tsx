import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { EntityProvider } from "./entities/EntityContext";
import "./index.css";
import { AppRoutes } from "./routes/AppRoutes";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <EntityProvider>
          <AppRoutes />
        </EntityProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
