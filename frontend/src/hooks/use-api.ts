"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface UseApiOptions {
  /** Auto-fetch on mount */
  immediate?: boolean;
  /** Polling interval in ms (0 = disabled) */
  pollInterval?: number;
}

interface UseApiReturn<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  options: UseApiOptions = {},
): UseApiReturn<T> {
  const { immediate = true, pollInterval = 0 } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(immediate);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (immediate) {
      refresh();
    }
  }, [immediate, refresh]);

  useEffect(() => {
    if (pollInterval <= 0) return;

    const interval = setInterval(refresh, pollInterval);
    return () => clearInterval(interval);
  }, [pollInterval, refresh]);

  return { data, error, loading, refresh };
}
