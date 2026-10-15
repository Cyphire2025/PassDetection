"use client";

import { useEffect, useRef, type RefObject } from "react";

interface StartRequest<T> { scope: string; controller: AbortController; promise: Promise<T>; consumers: number; delivered: boolean }

/** StrictMode effect replay shares one start; genuine scope changes create a new visit. */
export function useDraftInitialization<T>(load: (signal: AbortSignal) => Promise<T>, receive: (view: T) => void, controllerRef: RefObject<AbortController | null>, pending: (value: boolean) => void, report: (message: string) => void, errorMessage: (cause: unknown) => string, scope: string) {
  const request = useRef<StartRequest<T> | undefined>(undefined);
  useEffect(() => {
    const active = new AbortController(); controllerRef.current = active;
    if (request.current?.scope !== scope) {
      const controller = new AbortController();
      request.current = { scope, controller, promise: load(controller.signal), consumers: 0, delivered: false };
    }
    const started = request.current; started.consumers++;
    void started.promise.then((view) => { if (!active.signal.aborted && !started.delivered) { receive(view); started.delivered = true; } })
      .catch((cause) => { if (!active.signal.aborted) report(errorMessage(cause)); })
      .finally(() => { if (!active.signal.aborted) pending(false); });
    return () => {
      active.abort(); controllerRef.current = null; started.consumers--;
      queueMicrotask(() => { if (!started.consumers) started.controller.abort(); });
    };
  }, [load, receive, controllerRef, pending, report, errorMessage, scope]);
}
