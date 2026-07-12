import { useCallback, useEffect, useState } from "react";

import { toApiClientError, type ApiClientError } from "../api/client";

export interface AsyncData<T> {
  data: T | null;
  loading: boolean;
  error: ApiClientError | null;
  refresh: () => Promise<void>;
}

/**
 * Route/sayfa seviyesinde tekil okuma hook'u.
 *
 * 8A `active` kalıbını izler: unmount veya `deps` değişiminden sonra çözülen
 * eski isteğin sonucu **uygulanmaz** (stale guard). AbortController yoktur —
 * backend SQLite ölçekli ve ucuz; amaç eski veriyi state'e yazmamaktır, isteği
 * iptal etmek değil.
 */
export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
): AsyncData<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiClientError | null>(null);

  // `active` her efekt/refresh çağrısına özgüdür; kapanış üzerinden yakalanır.
  const load = useCallback(
    async (isActive: () => boolean) => {
      setLoading(true);
      setError(null);
      try {
        const result = await fetcher();
        if (!isActive()) return;
        setData(result);
      } catch (caught) {
        if (!isActive()) return;
        setError(toApiClientError(caught));
      } finally {
        if (isActive()) setLoading(false);
      }
    },
    // fetcher kimliği çağıranın sorumluluğunda; deps üzerinden yeniden koşar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    deps,
  );

  useEffect(() => {
    let active = true;
    void load(() => active);
    return () => {
      active = false;
    };
  }, [load]);

  const refresh = useCallback(async () => {
    let active = true;
    // refresh çağıran bileşen mount olduğu sürece geçerlidir; kısa ömürlü flag.
    await load(() => active);
    active = false;
  }, [load]);

  return { data, loading, error, refresh };
}
