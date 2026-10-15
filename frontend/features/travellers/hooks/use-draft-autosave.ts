"use client";
import { useEffect } from "react";

/** Debounced private persistence; flush on backgrounding and protect unsaved navigation. */
export function useDraftAutosave(dirty: boolean, payload: unknown, flush: () => Promise<void>) {
  useEffect(() => {
    if (!dirty || !payload) return;
    const persist = () => { void flush().catch(() => undefined); };
    const timer = window.setTimeout(persist, 800);
    const preventLoss = (event: BeforeUnloadEvent) => event.preventDefault();
    const saveOnHide = () => { if (document.hidden) persist(); };
    window.addEventListener("beforeunload", preventLoss);
    document.addEventListener("visibilitychange", saveOnHide);
    return () => { window.clearTimeout(timer); window.removeEventListener("beforeunload", preventLoss); document.removeEventListener("visibilitychange", saveOnHide); };
  }, [dirty, payload, flush]);
}
