import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { setApiNavigationErrorHandler } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../components/AppShell";
import { LoadingPanel } from "../components/Feedback";
import {
  ConflictPage,
  EntityCreatePage,
  EntityProfilePage,
  HomePage,
  LoginPage,
  LogoutPage,
  MePage,
  NotFoundPage,
  PermissionDeniedPage,
  RegisterPage,
  SessionRequiredPage,
} from "../pages";

function ApiErrorRedirector() {
  const navigate = useNavigate();
  useEffect(() => {
    setApiNavigationErrorHandler((error) => {
      const state = {
        code: error.code,
        requestId: error.requestId,
        userMessage: error.userMessage,
      };
      if (error.kind === "session_required") navigate("/session-required", { state });
      if (error.kind === "permission_denied") navigate("/permission-denied", { state });
      if (error.kind === "conflict") navigate("/conflict", { state });
    });
    return () => setApiNavigationErrorHandler(null);
  }, [navigate]);
  return null;
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingPanel label="Oturum doğrulanıyor…" />;
  if (!user) return <Navigate to="/session-required" replace />;
  return children;
}

export function AppRoutes() {
  return (
    <>
      <ApiErrorRedirector />
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="register" element={<RegisterPage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="logout" element={<RequireAuth><LogoutPage /></RequireAuth>} />
          <Route path="me" element={<RequireAuth><MePage /></RequireAuth>} />
          <Route path="entities/new" element={<RequireAuth><EntityCreatePage /></RequireAuth>} />
          <Route path="entities/:entityId" element={<RequireAuth><EntityProfilePage /></RequireAuth>} />
          <Route path="session-required" element={<SessionRequiredPage />} />
          <Route path="permission-denied" element={<PermissionDeniedPage />} />
          <Route path="conflict" element={<ConflictPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </>
  );
}
