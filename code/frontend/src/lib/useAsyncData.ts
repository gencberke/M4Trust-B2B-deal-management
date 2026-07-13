import { useCallback, useEffect, useRef, useState } from "react";

import { toApiClientError, type ApiClientError } from "../api/client";

export interface AsyncData<T> {
  data: T | null;
  loading: boolean;
  error: ApiClientError | null;
  refresh: () => Promise<void>;
}

/**
 * Route-level read hook with dependency reset, abort signalling, and a
 * monotonic generation guard. A late response can never overwrite data for a
 * newer acting entity, route parameter, or explicit refresh.
 */
export function useAsyncData<T>(
  fetcher: (signal?: AbortSignal) => Promise<T>,
  deps: unknown[],
  enabled = true,
): AsyncData<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<ApiClientError | null>(null);
  const generationRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async (reset: boolean) => {
      if (!enabled) {
        controllerRef.current?.abort();
        generationRef.current += 1;
        setData(null);
        setError(null);
        setLoading(false);
        return;
      }

      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      const generation = ++generationRef.current;
      if (reset) setData(null);
      setLoading(true);
      setError(null);

      try {
        const result = await fetcher(controller.signal);
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setData(result);
      } catch (caught) {
        if (controller.signal.aborted || generation !== generationRef.current) return;
        setError(toApiClientError(caught));
      } finally {
        if (!controller.signal.aborted && generation === generationRef.current) {
          setLoading(false);
        }
      }
    },
    // Callers intentionally define identity through deps; inline fetchers are supported.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [...deps, enabled],
  );

  useEffect(() => {
    void load(true);
    return () => {
      controllerRef.current?.abort();
      generationRef.current += 1;
    };
  }, [load]);

  const refresh = useCallback(async () => {
    await load(false);
  }, [load]);

  return { data, loading, error, refresh };
}
