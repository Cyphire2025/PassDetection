"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { DraftPayload, DraftSide } from "@/features/travellers/api/returning-draft.api";
import type { FreshMemberResume } from "@/features/travellers/services/draft-resume";
import { freshDraftApi, type FreshCollection, type FreshDraft, type FreshPayload } from "../api/fresh-draft.api";
import { freshError, freshPayload, reconcileFresh } from "../services/fresh-draft-state";
import { useDraftAutosave } from "@/features/travellers/hooks/use-draft-autosave";
import { useDraftPolling } from "@/features/travellers/hooks/use-draft-polling";
import { prepareDraftUpload, sendDraftUpload, type DraftUploadOperation } from "@/features/travellers/services/draft-upload-operation";
import { draftChecksPending } from "@/features/travellers/services/draft-check-state";
import { useDraftImageLifecycle } from "@/features/travellers/hooks/use-draft-image-lifecycle";
import { useDraftInitialization } from "@/features/travellers/hooks/use-draft-initialization";

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
  const retryUpload = useRef<DraftUploadOperation | null>(null);
  const adopt = useCallback((view: FreshDraft, base?: FreshPayload) => {
    if (current.current?.id === view.id && current.current.revision > view.revision) return;
    const merged = base && values.current ? reconcileFresh(base, values.current, freshPayload(view), true) : freshPayload(view);
    current.current = view; setDraft(view);
    values.current = merged; setPayload(merged);
  }, []);
  const load = useCallback(async (signal: AbortSignal) => {
    const view = await api.start(signal);
    return !view.collection && view.status === "active" ? api.save({ ...freshPayload(view), collection: initialValue.current }, view.revision, crypto.randomUUID(), signal) : view;
  }, [api]);
  const opened = useCallback((view: FreshDraft) => {
    version.current = 0; saved.current = 0; retrySave.current = null; retryUpload.current = null; queue.current = Promise.resolve(); setDirty(false); adopt(view);
  }, [adopt]);
  useDraftInitialization(load, opened, controller, setPending, setError, freshError, `${token}:${member.sessionId}:${attempt}`);
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
    adopt(result, request.payload); saved.current = request.version; retrySave.current = null; setDirty(saved.current !== version.current);
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
  const cancel = useCallback(() => controller.current?.abort(), []);
  const resume = useCallback(() => { setPending(true); setAttempt((value) => value + 1); }, []);
  const refresh = useCallback(() => serialized(async (signal) => {
    await save(signal); const base = values.current; const view = await api.read(signal);
    if (!signal.aborted) adopt(view, base);
  }), [serialized, save, api, adopt]);
  const syncContactRevision = useCallback(async (signal: AbortSignal) => {
    const base = current.current!, view = await api.read(signal);
    signal.throwIfAborted();
    if (view.id !== base.id || view.status !== "active" || view.revision < base.revision) throw new Error("This draft changed. Reopen it before continuing.");
    reconcileFresh(freshPayload(base), values.current!, freshPayload(view));
    adopt(view, freshPayload(base));
  }, [api, adopt]);
  const discard = useDraftImageLifecycle(current, draft, api, cancel, resume, `${token}:${member.sessionId}`, refresh);
  useDraftPolling(draftChecksPending(draft), refresh, setError, draft?.documents.map((item) => item.id).join(","));
  const upload = (side: DraftSide, file: File) => serialized(async (signal) => {
    await save(signal);
    const request = await prepareDraftUpload(retryUpload.current, side, file, current.current!);
    signal.throwIfAborted(); const base = values.current;
    retryUpload.current = request;
    const result = await sendDraftUpload(request, (operation) => api.upload(side, file, operation.revision, operation.key, signal, operation.assetId), () => api.read(signal),
      (operation) => { retryUpload.current = operation; }, (view) => adopt(view, base), signal);
    if (!signal.aborted) { adopt(result, base); retryUpload.current = null; return { documents: result.documents }; }
  }, true);
  const complete = (proof: string) => serialized(async (signal) => {
    await save(signal);
    if (saved.current !== version.current) throw new Error("Your latest edit is saving. Please retry submission.");
    const result = await api.complete(current.current!.revision, proof, member.submissionKey, signal);
    if (!signal.aborted) adopt(await api.start(signal));
    return result;
  }, true);
  const leave = () => serialized(async (signal) => {
    await save(signal);
    if (saved.current !== version.current) throw new Error("Your latest edit is saving. Please try again.");
    const base = values.current, view = await discard(signal);
    if (view && !signal.aborted) { adopt(view, base); retryUpload.current = null; }
  }, true);
  const retry = () => { if (current.current) void refresh().catch(() => undefined); else { setPending(true); setError(undefined); setAttempt((value) => value + 1); } };
  return { api, draft, payload, pending, dirty, error, update, collection, flush, refresh, syncContactRevision, retry, upload, complete, leave, serialized };
}
export type FreshDraftState = ReturnType<typeof useFreshDraft>;
