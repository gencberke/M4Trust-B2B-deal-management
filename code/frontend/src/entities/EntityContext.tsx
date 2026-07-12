import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { apiRequest, setApiActingEntityId } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import type { EntityPublic } from "../types/api";

const STORAGE_KEY = "m4t_acting_entity_id";

interface EntityContextValue {
  entities: EntityPublic[];
  selectedEntity: EntityPublic | null;
  selectedEntityId: string | null;
  loading: boolean;
  refreshEntities: () => Promise<EntityPublic[]>;
  selectEntity: (entityId: string | null) => void;
}

const EntityContext = createContext<EntityContextValue | null>(null);

export function EntityProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [entities, setEntities] = useState<EntityPublic[]>([]);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.localStorage.getItem(STORAGE_KEY),
  );
  const [loading, setLoading] = useState(false);

  const selectEntity = useCallback((entityId: string | null) => {
    setSelectedEntityId(entityId);
    setApiActingEntityId(entityId);
    if (typeof window !== "undefined") {
      if (entityId) window.localStorage.setItem(STORAGE_KEY, entityId);
      else window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const refreshEntities = useCallback(async () => {
    if (!user) {
      setEntities([]);
      selectEntity(null);
      return [];
    }

    setLoading(true);
    try {
      const result = await apiRequest<EntityPublic[]>("/entities");
      setEntities(result);
      const current =
        selectedEntityId && result.some((entity) => entity.id === selectedEntityId)
          ? selectedEntityId
          : result[0]?.id ?? null;
      selectEntity(current);
      return result;
    } finally {
      setLoading(false);
    }
  }, [selectEntity, selectedEntityId, user]);

  useEffect(() => {
    if (!user) {
      setEntities([]);
      selectEntity(null);
      return;
    }
    void refreshEntities();
  }, [refreshEntities, selectEntity, user]);

  const selectedEntity =
    entities.find((entity) => entity.id === selectedEntityId) ?? null;

  const value = useMemo(
    () => ({
      entities,
      selectedEntity,
      selectedEntityId,
      loading,
      refreshEntities,
      selectEntity,
    }),
    [entities, selectedEntity, selectedEntityId, loading, refreshEntities, selectEntity],
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
