import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  ApiClientError,
  apiRequest,
  setApiActingEntityId,
  toApiClientError,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { EntityPublic } from "../types/api";

const STORAGE_KEY = "m4t_acting_entity_id";

export type EntityBootstrapResult =
  | { kind: "success"; entities: EntityPublic[]; error: null }
  | { kind: "auth_required"; entities: []; error: null }
  | { kind: "error"; entities: []; error: ApiClientError };

type EntityRequester = () => Promise<EntityPublic[]>;

export async function resolveEntityBootstrap(
  requestEntities: EntityRequester = () => apiRequest<EntityPublic[]>("/entities"),
): Promise<EntityBootstrapResult> {
  try {
    const entities = await requestEntities();
    return { kind: "success", entities, error: null };
  } catch (caught) {
    const error = toApiClientError(caught);
    if (error.kind === "session_required" && error.status === 401) {
      return { kind: "auth_required", entities: [], error: null };
    }
    return { kind: "error", entities: [], error };
  }
}

interface EntityContextValue {
  entities: EntityPublic[];
  selectedEntity: EntityPublic | null;
  selectedEntityId: string | null;
  loading: boolean;
  error: ApiClientError | null;
  refreshEntities: () => Promise<EntityPublic[]>;
  selectEntity: (entityId: string | null) => void;
}

const EntityContext = createContext<EntityContextValue | null>(null);

export function EntityProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const initialEntityId =
    typeof window === "undefined" ? null : window.localStorage.getItem(STORAGE_KEY);
  const [entities, setEntities] = useState<EntityPublic[]>([]);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(initialEntityId);
  const selectedEntityIdRef = useRef<string | null>(initialEntityId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiClientError | null>(null);

  const selectEntity = useCallback((entityId: string | null) => {
    selectedEntityIdRef.current = entityId;
    setSelectedEntityId(entityId);
    setApiActingEntityId(entityId);
    if (typeof window !== "undefined") {
      if (entityId) window.localStorage.setItem(STORAGE_KEY, entityId);
      else window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const applyEntities = useCallback(
    (result: EntityPublic[]) => {
      setEntities(result);
      const preferred = selectedEntityIdRef.current;
      const current =
        preferred && result.some((entity) => entity.id === preferred)
          ? preferred
          : result[0]?.id ?? null;
      selectEntity(current);
    },
    [selectEntity],
  );

  const refreshEntities = useCallback(async () => {
    if (!user) {
      setEntities([]);
      setError(null);
      selectEntity(null);
      return [];
    }

    setLoading(true);
    setError(null);
    const result = await resolveEntityBootstrap();
    if (result.kind === "success") {
      applyEntities(result.entities);
      setLoading(false);
      return result.entities;
    }

    setEntities([]);
    selectEntity(null);
    if (result.kind === "error") setError(result.error);
    setLoading(false);
    return [];
  }, [applyEntities, selectEntity, user]);

  useEffect(() => {
    let active = true;
    void (async () => {
      await Promise.resolve();
      if (!active) return;
      if (!user) {
        setEntities([]);
        setError(null);
        selectEntity(null);
        return;
      }

      setLoading(true);
      setError(null);
      const result = await resolveEntityBootstrap();
      if (!active) return;
      if (result.kind === "success") {
        applyEntities(result.entities);
      } else {
        setEntities([]);
        selectEntity(null);
        if (result.kind === "error") setError(result.error);
      }
      setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, [applyEntities, selectEntity, user]);

  const selectedEntity =
    entities.find((entity) => entity.id === selectedEntityId) ?? null;

  const value = useMemo(
    () => ({
      entities,
      selectedEntity,
      selectedEntityId,
      loading,
      error,
      refreshEntities,
      selectEntity,
    }),
    [
      entities,
      selectedEntity,
      selectedEntityId,
      loading,
      error,
      refreshEntities,
      selectEntity,
    ],
  );

  return <EntityContext.Provider value={value}>{children}</EntityContext.Provider>;
}

export function useEntities(): EntityContextValue {
  const context = useContext(EntityContext);
  if (!context) {
    throw new Error("useEntities, EntityProvider içinde kullanılmalıdır.");
  }
  return context;
}
