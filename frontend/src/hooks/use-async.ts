"use client";

import { useCallback, useEffect, useState } from "react";
import { isAbort } from "@/lib/api";

export interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload(): void;
}

/** Loads something once on mount, and again when `reload` is called. */
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>): AsyncState<T> {
  const [state, setState] = useState<{ data: T | null; error: Error | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error: unknown) => {
        if (isAbort(error)) return;
        setState({ data: null, error: error instanceof Error ? error : new Error(String(error)), loading: false });
      });
    return () => controller.abort();
    // `load` is expected to be stable for the lifetime of the component.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    setAttempt((n) => n + 1);
  }, []);

  return { ...state, reload };
}
