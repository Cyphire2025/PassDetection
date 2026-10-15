"use client";

import { useCallback, useEffect, useRef, type RefObject } from "react";
import type { DraftImageActivity } from "../api/draft-image-lifecycle.api";

interface ImageView { id: string; revision: number; status: string; documents: unknown[] }
interface ImageApi<T> { discard: (revision: number, signal?: AbortSignal, keepalive?: boolean) => Promise<T | undefined>; activity: (signal?: AbortSignal) => Promise<DraftImageActivity> }

/** Text remains resumable; document bytes belong only to this active form visit. */
export function useDraftImageLifecycle<T extends ImageView>(viewRef: RefObject<T | undefined>, view: T | undefined, api: ImageApi<T>, cancel: () => void, resume: () => void, visit = "", refresh?: () => Promise<unknown>) {
  const disposed = useRef<string | undefined>(undefined);
  const visits = useRef(new Map<string, { users: number }>());
  const discard = useCallback(async (signal?: AbortSignal, keepalive = false, latest = viewRef.current) => {
    if (!latest || latest.status !== "active") return;
    const key = `${latest.id}:${latest.revision}`;
    if (disposed.current === key) return;
    const result = await api.discard(latest.revision, signal, keepalive);
    disposed.current = `${latest.id}:${result?.revision ?? latest.revision}`;
    return result;
  }, [api, viewRef]);
  useEffect(() => {
    const registry = visits.current, latestView = () => viewRef.current;
    const mounted = registry.get(visit) ?? { users: 0 }; mounted.users++; registry.set(visit, mounted);
    const leave = () => { cancel(); void discard(undefined, true).catch(() => undefined); };
    const restore = (event: PageTransitionEvent) => { if (event.persisted) resume(); };
    window.addEventListener("pagehide", leave); window.addEventListener("pageshow", restore);
    return () => {
      window.removeEventListener("pagehide", leave); window.removeEventListener("pageshow", restore); mounted.users--;
      const latest = latestView();
      queueMicrotask(() => { if (!mounted.users) { registry.delete(visit); void discard(undefined, true, latest).catch(() => undefined); } });
    };
  }, [discard, cancel, resume, visit, viewRef]);
  useEffect(() => {
    if (view?.status !== "active" || !view.documents.length) return;
    const active = new AbortController(); let inFlight = false;
    const heartbeat = async () => {
      if (document.hidden || inFlight) return;
      inFlight = true;
      try { await api.activity(active.signal).then((presence) => { if (presence.images_present === false && !active.signal.aborted) return refresh?.(); }); }
      catch { /* The server lease expires if this visit is disconnected. */ }
      finally { inFlight = false; }
    };
    void heartbeat(); const timer = setInterval(() => void heartbeat(), 60_000);
    const visible = () => { if (!document.hidden) void heartbeat(); };
    document.addEventListener("visibilitychange", visible);
    return () => { active.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [api, view?.id, view?.status, view?.documents.length, refresh]);
  return discard;
}
