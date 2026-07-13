import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { probeDemoStatus } from "../api/demo";
import { useAuth } from "../auth/AuthContext";

interface DemoContextValue { enabled: boolean; loading: boolean }
const DemoContext = createContext<DemoContextValue>({ enabled: false, loading: false });

export function DemoProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    setEnabled(false);
    if (authLoading || !user) return () => { active = false; };
    setLoading(true);
    void probeDemoStatus().then((status) => { if (active) setEnabled(status?.demo_tools_enabled === true); })
      .catch(() => { if (active) setEnabled(false); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [authLoading, user]);
  const value = useMemo(() => ({ enabled, loading }), [enabled, loading]);
  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}

export function useDemo(): DemoContextValue { return useContext(DemoContext); }
