"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { returningDraftApi, type DraftPayload, type DraftSide, type ReturningDraft } from "../api/returning-draft.api";
import { clearDraftResume, saveDraftResume } from "../services/draft-resume";
import { freshPayload as payloadOf, reconcileFresh } from "@/features/upload/services/fresh-draft-state";
import type { FreshCollection, FreshPayload } from "@/features/upload/api/fresh-draft.api";
import { useDraftAutosave } from "./use-draft-autosave";
import type { ReturningHistory, ReturningOwnedSource } from "../types";

const messageOf = (cause: unknown) => cause && typeof cause === "object" && "message" in cause && typeof cause.message === "string" ? cause.message : "Your draft could not be saved. Keep this page open and retry.";

/** Serial revisions prevent autosave, upload, OTP and final-submit races. */
export function useReturningDraft(history: ReturningHistory, token: string, ownedSource?: ReturningOwnedSource) {
  const [draft, setDraft] = useState<ReturningDraft>();
  const [payload, setPayload] = useState<FreshPayload>();
  const [pending, setPending] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string>();
  const current = useRef<ReturningDraft | undefined>(undefined);
  const values = useRef<FreshPayload | undefined>(undefined);
  const version = useRef(0);
  const savedVersion = useRef(0);
  const saveRequest = useRef<{ payload: FreshPayload; base: FreshPayload; revision: number; key: string; version: number } | null>(null);
  const uploadRequest = useRef<{ side: DraftSide; file: File; revision: number; key: string } | null>(null);
  const controller = useRef<AbortController | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const submitKey = useRef(crypto.randomUUID());
  const adopt = useCallback((view: ReturningDraft, replace = true) => {
    current.current = view; setDraft(view);
    if (replace) { values.current = payloadOf(view); setPayload(values.current); }
  }, []);
  useEffect(() => {
    const active = new AbortController(); controller.current = active;
    void returningDraftApi.start(history.review_version, active.signal).then((view) => {
      if (!active.signal.aborted) { adopt(view); if (view.status === "submitted") clearDraftResume(token); else submitKey.current = saveDraftResume(token, view.expires_at, "returning").submissionKey; }
    }).catch((cause) => { if (!active.signal.aborted) setError(messageOf(cause)); }).finally(() => { if (!active.signal.aborted) setPending(false); });
    return () => { active.abort(); controller.current = null; };
  }, [history.review_version, token, adopt, attempt]);

  const serialized = useCallback(<T,>(operation: (signal: AbortSignal) => Promise<T>, foreground = false): Promise<T> => {
    const signal = controller.current?.signal;
    const result = queue.current.catch(() => undefined).then(async () => {
      if (!signal || signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (foreground) setPending(true);
      setError(undefined);
      try { return await operation(signal); }
      catch (cause) { if (!signal.aborted) setError(messageOf(cause)); throw cause; }
      finally { if (foreground && !signal.aborted) setPending(false); }
    });
    queue.current = result;
    return result;
  }, []);
  const save = useCallback(async (signal: AbortSignal) => {
    if (!current.current || !values.current) throw new Error("The secure draft is still loading.");
    if (savedVersion.current === version.current) return;
    const request = saveRequest.current ?? { payload: values.current, base: payloadOf(current.current), revision: current.current.revision, key: crypto.randomUUID(), version: version.current };
    saveRequest.current = request;
    let result: ReturningDraft;
    try { result = await returningDraftApi.save(request.payload, request.revision, request.key, current.current.id, signal); }
    catch (cause) {
      if (!cause || typeof cause !== "object" || !("status" in cause) || cause.status !== 409) throw cause;
      const remote = await returningDraftApi.read(current.current.id, signal);
      if (remote.id !== current.current.id || remote.status !== "active") throw cause;
      const merged = reconcileFresh(request.base, request.payload, payloadOf(remote));
      const retry = { payload: merged, base: payloadOf(remote), revision: remote.revision, key: crypto.randomUUID(), version: request.version };
      saveRequest.current = retry;
      result = await returningDraftApi.save(retry.payload, retry.revision, retry.key, current.current.id, signal);
    }
    if (signal.aborted) return;
    if (request.version !== version.current) {
      values.current = reconcileFresh(request.payload, values.current, payloadOf(result));
      setPayload(values.current);
    }
    adopt(result, request.version === version.current); savedVersion.current = request.version; saveRequest.current = null;
    setDirty(savedVersion.current !== version.current);
  }, [adopt]);
  const flush = useCallback(() => serialized(save), [serialized, save]);
  const update = useCallback((section: keyof DraftPayload, key: string, value: string) => {
    if (!values.current) return;
    values.current = { ...values.current, [section]: { ...values.current[section], [key]: value } };
    version.current++; setPayload(values.current); setDirty(true);
  }, []);
  const collection = useCallback((patch: Partial<FreshCollection>) => {
    if (!values.current) return;
    values.current = { ...values.current, collection: { acquisition_mode: "file", submission_mode: "single", ...values.current.collection, ...patch } };
    version.current++; setPayload(values.current); setDirty(true);
  }, []);
  useDraftAutosave(dirty, payload, flush);
  const refresh = useCallback(() => serialized(async (signal) => {
    await save(signal); const view = await returningDraftApi.read(current.current!.id, signal);
    if (!signal.aborted) adopt(view, version.current === savedVersion.current);
  }), [serialized, save, adopt]);
  useEffect(() => {
    if (draft?.extraction_status !== "pending" && draft?.extraction_status !== "running") return;
    let polls = 0;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      if (++polls > 20) { window.clearInterval(timer); setError("Reading this page is taking longer than usual. Select Retry to check its progress."); return; }
      void refresh().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [draft?.extraction_status, refresh]);
  const upload = useCallback((side: DraftSide, file: File) => serialized(async (signal) => {
    await save(signal);
    const prior = uploadRequest.current;
    const sameFile = prior?.side === side && prior.file.name === file.name && prior.file.size === file.size && prior.file.lastModified === file.lastModified;
    const request = sameFile ? prior : { side, file, revision: current.current!.revision, key: crypto.randomUUID() };
    uploadRequest.current = request;
    let result: ReturningDraft;
    try { result = await returningDraftApi.upload(side, file, request.revision, request.key, current.current!.id, signal); }
    catch (cause) {
      if (cause && typeof cause === "object" && "status" in cause && cause.status === 409) uploadRequest.current = null;
      throw cause;
    }
    uploadRequest.current = null;
    if (!signal.aborted) adopt(result, version.current === savedVersion.current);
  }, true), [serialized, save, adopt]);
  const complete = useCallback(() => serialized(async (signal) => {
    await save(signal);
    if (savedVersion.current !== version.current) throw new Error("Your latest edit is still saving. Please retry submission.");
    const result = await returningDraftApi.complete({ expected_revision: current.current!.revision,
      review_version: history.review_version, question_version: history.question_version,
      ...(history.participation_revision != null ? { expected_participation_revision: history.participation_revision } : {}),
      ...(ownedSource ? { owned_source: { source_submission_id: ownedSource.source_submission_id, expected_extraction_revision: ownedSource.expected_extraction_revision } } : {}),
      information_confirmed: true, idempotency_key: submitKey.current }, current.current!.id, signal, ownedSource?.uploadSessionId);
    if (ownedSource && !result.source_submission_id) throw new Error("Your saved details could not be linked to this upload. Please retry submission.");
    if (!signal.aborted) clearDraftResume(token);
    return result;
  }, true), [serialized, save, history, token, ownedSource]);
  const retry = () => {
    if (current.current) { void refresh().catch(() => undefined); return; }
    setPending(true); setError(undefined); setAttempt((value) => value + 1);
  };
  return { draft, payload, pending, dirty, error, update, collection, flush, refresh, retry, upload, complete, serialized };
}
