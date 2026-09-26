"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { uploadOperationReducer, type UploadOperationKind } from "../services/upload-operation-state";

export type UploadOperation = { generation: number; controller: AbortController };

/** Synchronous admission plus a renderable reducer; promises cannot unlock a newer operation. */
export function useUploadOperation(scope = "") {
  const [state, dispatch] = useReducer(uploadOperationReducer, { status: "idle", generation: 0 });
  const active = useRef<UploadOperation | null>(null);
  const nextGeneration = useRef(0);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    dispatch({ type: "finished", generation: nextGeneration.current });
    return () => { mounted.current = false; active.current?.controller.abort(); active.current = null; };
  }, [scope]);
  const begin = useCallback((kind: UploadOperationKind) => {
    if (!mounted.current || active.current) return null;
    const operation = { generation: ++nextGeneration.current, controller: new AbortController() };
    active.current = operation;
    dispatch({ type: "started", generation: operation.generation, kind });
    return operation;
  }, []);
  const isCurrent = useCallback((operation: UploadOperation) => (
    mounted.current && active.current === operation && !operation.controller.signal.aborted
  ), []);
  const finish = useCallback((operation: UploadOperation) => {
    if (active.current !== operation) return;
    active.current = null;
    if (mounted.current) dispatch({ type: "finished", generation: operation.generation });
  }, []);
  const cancel = useCallback(() => {
    const operation = active.current;
    if (!operation) return;
    operation.controller.abort();
    active.current = null;
    if (mounted.current) dispatch({ type: "finished", generation: operation.generation });
  }, []);
  const isBusy = useCallback(() => active.current !== null, []);
  return { state, begin, isCurrent, finish, cancel, isBusy };
}
