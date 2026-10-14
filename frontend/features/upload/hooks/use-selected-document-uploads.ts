"use client";
import { useEffect, useRef, useState } from "react";
import type { DraftSide } from "@/features/travellers/api/returning-draft.api";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { preparePublicUploadFile } from "../services/public-upload-file";
import { freshError } from "../services/fresh-draft-state";
type Selection = { file: File; assetId?: string };

/** Selected files live only in this mounted form, never in browser draft storage. */
export function useSelectedDocumentUploads(state: DraftDocumentInputs, token: string, sessionId: string) {
  const [selections, setSelected] = useState<Partial<Record<DraftSide, Selection>>>({});
  const [pendingSide, setPendingSide] = useState<DraftSide>();
  const [error, setError] = useState<string>();
  const operation = useRef<AbortController | null>(null);
  useEffect(() => {
    const leave = () => {
      operation.current?.abort(); operation.current = null;
      setSelected({}); setPendingSide(undefined); setError(undefined);
    };
    window.addEventListener("pagehide", leave);
    return () => { operation.current?.abort(); window.removeEventListener("pagehide", leave); };
  }, []);
  const upload = async (side: DraftSide, file: File, source: "file" | "camera") => {
    // One transfer at a time; selecting another file cannot silently cancel the first.
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller;
    setPendingSide(side); setError(undefined); setSelected((value) => ({ ...value, [side]: { file } }));
    try {
      const ready = source === "file" ? await preparePublicUploadFile(file, { token, uploadSessionId: sessionId, purpose: side === "photo" ? "visa" : "passport", signal: controller.signal }) : file;
      if (controller.signal.aborted) return;
      setSelected((value) => ({ ...value, [side]: { file: ready } }));
      state.collection(side === "photo" ? { visa_photo_source: source } : { acquisition_mode: source });
      const receipt = await state.upload(side, ready);
      if (controller.signal.aborted) return;
      const accepted = receipt?.documents.find((document) => document.side === side);
      setSelected((value) => ({ ...value, [side]: accepted ? { file: ready, assetId: accepted.id } : undefined }));
    } catch (cause) {
      if (!controller.signal.aborted) { setError(freshError(cause)); setSelected((value) => ({ ...value, [side]: undefined })); }
    } finally {
      if (operation.current === controller) operation.current = null;
      if (!controller.signal.aborted) setPendingSide(undefined);
    }
  };
  const selected = Object.fromEntries(Object.entries(selections).filter(([side, value]) => value && (!value.assetId || state.draft?.documents.some((document) => document.side === side && document.id === value.assetId))).map(([side, value]) => [side, value!.file])) as Partial<Record<DraftSide, File>>;
  return { selected, pendingSide, error, upload };
}
