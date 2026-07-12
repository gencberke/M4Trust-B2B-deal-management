import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiClientError, apiRequest, toApiClientError } from "../api/client";
import type { LoginRequest, RegisterRequest, UserPublic } from "../types/api";

export type AuthBootstrapResult =
  | { kind: "authenticated"; user: UserPublic; error: null }
  | { kind: "anonymous"; user: null; error: null }
  | { kind: "error"; user: null; error: ApiClientError };

type CurrentUserRequester = () => Promise<UserPublic>;

export async function resolveAuthBootstrap(
  requestCurrentUser: CurrentUserRequester = () =>
    apiRequest<UserPublic>("/auth/me", { redirectOnError: false }),
): Promise<AuthBootstrapResult> {
  try {
    const user = await requestCurrentUser();
    return { kind: "authenticated", user, error: null };
  } catch (caught) {
    const error = toApiClientError(caught);
    if (error.kind === "session_required" && error.status === 401) {
      return { kind: "anonymous", user: null, error: null };
    }
    return { kind: "error", user: null, error };
  }
}

interface AuthContextValue {
  user: UserPublic | null;
  loading: boolean;
  bootstrapError: ApiClientError | null;
  refresh: () => Promise<UserPublic | null>;
  register: (input: RegisterRequest) => Promise<UserPublic>;
  login: (input: LoginRequest) => Promise<UserPublic>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const [bootstrapError, setBootstrapError] = useState<ApiClientError | null>(null);

  const applyBootstrapResult = useCallback((result: AuthBootstrapResult) => {
    if (result.kind === "authenticated") {
      setUser(result.user);
    } else if (result.kind === "anonymous") {
      setUser(null);
    } else {
      setBootstrapError(result.error);
    }
  }, []);

  const refresh = useCallback(async (): Promise<UserPublic | null> => {
    setLoading(true);
    setBootstrapError(null);
    const result = await resolveAuthBootstrap();
    applyBootstrapResult(result);
    setLoading(false);
    return result.user;
  }, [applyBootstrapResult]);

  useEffect(() => {
    let active = true;
    void resolveAuthBootstrap().then((result) => {
      if (!active) return;
      applyBootstrapResult(result);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [applyBootstrapResult]);

  const register = useCallback(async (input: RegisterRequest) => {
    return apiRequest<UserPublic>("/auth/register", {
      method: "POST",
      body: input,
      redirectOnError: false,
    });
  }, []);

  const login = useCallback(async (input: LoginRequest) => {
    const loggedInUser = await apiRequest<UserPublic>("/auth/login", {
      method: "POST",
      body: input,
      redirectOnError: false,
    });
    setUser(loggedInUser);
    setBootstrapError(null);
    setLoading(false);
    return loggedInUser;
  }, []);

  const logout = useCallback(async () => {
    await apiRequest<void>("/auth/logout", {
      method: "POST",
      csrf: true,
      redirectOnError: false,
    });
    setUser(null);
    setBootstrapError(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, bootstrapError, refresh, register, login, logout }),
    [user, loading, bootstrapError, refresh, register, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth, AuthProvider içinde kullanılmalıdır.");
  }
  return context;
}
