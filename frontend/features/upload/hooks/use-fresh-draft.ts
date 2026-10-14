"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DraftPayload, DraftSide } from "@/features/travellers/api/returning-draft.api";
import type { FreshMemberResume } from "@/features/travellers/services/draft-resume";
import { freshDraftApi, type FreshCollection, type FreshDraft, type FreshPayload } from "../api/fresh-draft.api";
import { freshError, freshPayload, reconcileFresh } from "../services/fresh-draft-state";
import { useDraftAutosave } from "@/features/travellers/hooks/use-draft-autosave";

/** One serial revision stream per family member. Personal fields never enter browser storage. */
export function useFreshDraft(token: string, member: FreshMemberResume, initial: FreshCollection) {
  const api = useMemo(() => freshDraftApi(token, member.sessionId), [token, member.sessionId]);
  const [draft, setDraft] = useState<FreshDraft>();
  const [payload, setPayload] = useState<FreshPayload>();
  const [pending, setPending] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const current = useRef<FreshDraft | undefined>(undefined), values = useRef<FreshPayload | undefined>(undefined);
  const version = useRef(0), saved = useRef(0), queue = useRef<Promise<unknown>>(Promise.resolve());
  const controller = useRef<AbortController | null>(null), initialValue = useRef(initial);
  const retrySave = useRef<{ payload: FreshPayload; base: FreshPayload; revision: number; key: string; version: number } | null>(null);
  const retryUpload = useRef<{ side: DraftSide; file: File; revision: number; key: string } | null>(null);
  const adopt = useCallback((view: FreshDraft, replace = true) => {
    current.current = view; setDraft(view);
    if (replace) { values.current = freshPayload(view); setPayload(values.current); }
  }, []);
  useEffect(() => {
    const active = new AbortController(); controller.current = active;
    void api.start(active.signal).then(async (view) => {
      if (!view.collection && view.status === "active") view = await api.save({ ...freshPayload(view), collection: initialValue.current }, view.revision, crypto.randomUUID(), active.signal);
      if (!active.signal.aborted) adopt(view);
    }).catch((cause) => { if (!active.signal.aborted) setError(freshError(cause)); }).finally(() => { if (!active.signal.aborted) setPending(false); });
    return () => { active.abort(); controller.current = null; };
  }, [api, adopt, attempt]);
  const serialized = useCallback(<T,>(operation: (signal: AbortSignal) => Promise<T>, foreground = false): Promise<T> => {
    const signal = controller.current?.signal;
    const result = queue.current.catch(() => undefined).then(async () => {
      if (!signal || signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (foreground) setPending(true);
      setError(undefined);
      try { return await operation(signal); }
      catch (cause) { if (!signal.aborted) setError(freshError(cause)); throw cause; }
      finally { if (foreground && !signal.aborted) setPending(false); }
    });
    queue.current = result; return result;
  }, []);
  const save = useCallback(async (signal: AbortSignal) => {
    if (!current.current || !values.current) throw new Error("Your private draft is still loading.");
    if (version.current === saved.current) return;
    const request = retrySave.current ?? { payload: values.current, base: freshPayload(current.current), revision: current.current.revision, key: crypto.randomUUID(), version: version.current };
    retrySave.current = request;
    let result: FreshDraft;
    try { result = await api.save(request.payload, request.revision, request.key, signal); }
    catch (cause) {
      if (!cause || typeof cause !== "object" || !("status" in cause) || cause.status !== 409) throw cause;
      const remote = await api.read(signal);
      if (remote.id !== current.current.id || remote.status !== "active") throw cause;
      const retry = { ...request, payload: reconcileFresh(request.base, request.payload, freshPayload(remote)), base: freshPayload(remote), revision: remote.revision, key: crypto.randomUUID() };
      retrySave.current = retry; result = await api.save(retry.payload, retry.revision, retry.key, signal);
    }
    if (signal.aborted) return;
    if (request.version !== version.current) { values.current = reconcileFresh(request.payload, values.current, freshPayload(result)); setPayload(values.current); }
    adopt(result, request.version === version.current); saved.current = request.version; retrySave.current = null; setDirty(saved.current !== version.current);
  }, [api, adopt]);
  const flush = useCallback(() => serialized(save), [serialized, save]);
  const update = useCallback((section: keyof DraftPayload, key: string, value: string) => {
    if (!values.current) return;
    values.current = { ...values.current, [section]: { ...values.current[section], [key]: value } };
    version.current++; setPayload(values.current); setDirty(true);
  }, []);
  const collection = useCallback((patch: Partial<FreshCollection>) => {
    if (!values.current) return;
    if (Object.entries(patch).every(([key, value]) => values.current?.collection?.[key as keyof FreshCollection] === value)) return;
    values.current = { ...values.current, collection: { ...initialValue.current, ...values.current.collection, ...patch } };
    version.current++; setPayload(values.current); setDirty(true);
  }, []);
  useDraftAutosave(dirty, payload, flush);
  const refresh = useCallback(() => serialized(async (signal) => {
    await save(signal); const view = await api.read(signal);
    if (!signal.aborted) adopt(view, version.current === saved.current);
  }), [serialized, save, api, adopt]);
  useEffect(() => {
    if (draft?.extraction_status !== "pending" && draft?.extraction_status !== "running") return;
    let polls = 0;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      if (++polls > 20) { window.clearInterval(timer); setError("The document check is taking longer than usual. Select Retry to check again."); return; }
      void refresh().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [draft?.extraction_status, refresh]);
  const upload = (side: DraftSide, file: File) => serialized(async (signal) => {
    await save(signal);
    const previous = retryUpload.current;
    const same = previous?.side === side && previous.file.name === file.name && previous.file.size === file.size && previous.file.lastModified === file.lastModified;
    const request = same ? previous : { side, file, revision: current.current!.revision, key: crypto.randomUUID() };
    retryUpload.current = request;
    try {
      const result = await api.upload(side, file, request.revision, request.key, signal);
      if (!signal.aborted) { adopt(result, version.current === saved.current); retryUpload.current = null; }
    } catch (cause) {
      if (cause && typeof cause === "object" && "status" in cause && cause.status === 409) { retryUpload.current = null; const view = await api.read(signal); if (!signal.aborted) adopt(view, version.current === saved.current); throw new Error("This draft changed. Review the latest details, then choose the image again."); }
      throw cause;
    }
  }, true);
  const complete = (proof: string) => serialized(async (signal) => {
    await save(signal);
    if (saved.current !== version.current) throw new Error("Your latest edit is saving. Please retry submission.");
    const result = await api.complete(current.current!.revision, proof, member.submissionKey, signal);
    if (!signal.aborted) adopt(await api.start(signal));
    return result;
  }, true);
  const retry = () => { if (current.current) void refresh().catch(() => undefined); else { setPending(true); setError(undefined); setAttempt((value) => value + 1); } };
  return { api, draft, payload, pending, dirty, error, update, collection, flush, refresh, retry, upload, complete, serialized };
}
export type FreshDraftState = ReturnType<typeof useFreshDraft>;
