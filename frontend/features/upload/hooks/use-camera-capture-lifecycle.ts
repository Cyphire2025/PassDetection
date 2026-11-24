"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

/** A capture may finish after its camera closes or restarts. Only its owner can publish it. */
export function useCameraCaptureLifecycle() {
  const state = useRef({ mounted: false, generation: 0 });

  useEffect(() => {
    const lifecycle = state.current;
    lifecycle.mounted = true;
    return () => {
      lifecycle.mounted = false;
      lifecycle.generation += 1;
    };
  }, []);

  const invalidate = useCallback(() => {
    state.current.generation += 1;
  }, []);

  const begin = useCallback(() => {
    const generation = state.current.generation;
    return () => state.current.mounted && state.current.generation === generation;
  }, []);

  return useMemo(() => ({ begin, invalidate }), [begin, invalidate]);
}
