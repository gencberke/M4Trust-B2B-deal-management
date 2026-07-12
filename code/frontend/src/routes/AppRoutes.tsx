import { useEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { setApiNavigationErrorHandler } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../components/AppShell";
import { TransactionShell } from "../components/TransactionShell";
import { LoadingPanel, RetryPanel } from "../components/Feedback";
import {
  ConflictPage,
  EntityCreatePage,
  EntityProfilePage,
  HomePage,
  InvitationPage,
  LoginPage,
  LogoutPage,
  MePage,
  NotFoundPage,
  PermissionDeniedPage,
  RegisterPage,
  SessionRequiredPage,
  TransactionCreatePage,
  TransactionListPage,
  TransactionOverviewPage,
  TransactionPartiesPage,
  TransactionRulesPage,
} from "../pages";
import { buildApiErrorNavigationState } from "./navigation";

function ApiErrorRedirector() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    setApiNavigationErrorHandler((error) => {
      const sourcePath = `${location.pathname}${location.search}${location.hash}`;
      const state = buildApiErrorNavigationState(error, sourcePath);
      if (error.kind === "session_required") navigate("/session-required", { state });
      if (error.kind === "permission_denied") navigate("/permission-denied", { state });
      if (error.kind === "conflict") navigate("/conflict", { state });
    });
    return () => setApiNavigationErrorHandler(null);
  }, [location.hash, location.pathname, location.search, navigate]);
  return null;
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, bootstrapError, refresh } = useAuth();
  if (loading) return <LoadingPanel label="Oturum doğrulanıyor…" />;
  if (bootstrapError) {
    return (
      <RetryPanel
        title="Oturum doğrulanamadı"
        message={bootstrapError.userMessage}
        onRetry={() => void refresh()}
      />
    );
  }
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
          <Route path="transactions" element={<RequireAuth><TransactionListPage /></RequireAuth>} />
          <Route path="transactions/new" element={<RequireAuth><TransactionCreatePage /></RequireAuth>} />
          <Route path="transactions/:transactionId" element={<RequireAuth><TransactionShell /></RequireAuth>}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<TransactionOverviewPage />} />
            <Route path="parties" element={<TransactionPartiesPage />} />
            <Route path="rules" element={<TransactionRulesPage />} />
          </Route>
          <Route path="invitations/:token" element={<InvitationPage />} />
          <Route path="session-required" element={<SessionRequiredPage />} />
          <Route path="permission-denied" element={<PermissionDeniedPage />} />
          <Route path="conflict" element={<ConflictPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </>
  );
}
