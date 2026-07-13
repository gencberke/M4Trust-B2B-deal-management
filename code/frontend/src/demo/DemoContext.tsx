import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { probeDemoStatus } from "../api/demo";
import { useAuth } from "../auth/AuthContext";

interface DemoContextValue { enabled: boolean; loading: boolean }
const DemoContext = createContext<DemoContextValue>({ enabled: false, loading: false });

export function DemoProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [status, setStatus] = useState<{ userId: string; enabled: boolean } | null>(null);
  useEffect(() => {
    let active = true;
    if (authLoading || !user) return () => { active = false; };
    void probeDemoStatus().then((result) => {
      if (active) setStatus({ userId: user.id, enabled: result?.demo_tools_enabled === true });
    }).catch(() => {
      if (active) setStatus({ userId: user.id, enabled: false });
    });
    return () => { active = false; };
  }, [authLoading, user]);
  const enabled = Boolean(user && status?.userId === user.id && status.enabled);
  const loading = Boolean(authLoading || (user && status?.userId !== user.id));
  const value = useMemo(() => ({ enabled, loading }), [enabled, loading]);
  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}

export function useDemo(): DemoContextValue { return useContext(DemoContext); }
