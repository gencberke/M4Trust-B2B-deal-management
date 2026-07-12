import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiClientError, apiRequest } from "../api/client";
import type { LoginRequest, RegisterRequest, UserPublic } from "../types/api";

interface AuthContextValue {
  user: UserPublic | null;
  loading: boolean;
  refresh: () => Promise<UserPublic | null>;
  register: (input: RegisterRequest) => Promise<UserPublic>;
  login: (input: LoginRequest) => Promise<UserPublic>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (): Promise<UserPublic | null> => {
    try {
      const currentUser = await apiRequest<UserPublic>("/auth/me", {
        redirectOnError: false,
      });
      setUser(currentUser);
      return currentUser;
    } catch (error) {
      if (error instanceof ApiClientError && error.kind === "session_required") {
        setUser(null);
        return null;
      }
      throw error;
    }
  }, []);

  useEffect(() => {
    let active = true;
    void apiRequest<UserPublic>("/auth/me", { redirectOnError: false })
      .then((currentUser) => {
        if (active) setUser(currentUser);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

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
    return loggedInUser;
  }, []);

  const logout = useCallback(async () => {
    await apiRequest<void>("/auth/logout", {
      method: "POST",
      csrf: true,
      redirectOnError: false,
    });
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, refresh, register, login, logout }),
    [user, loading, refresh, register, login, logout],
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
