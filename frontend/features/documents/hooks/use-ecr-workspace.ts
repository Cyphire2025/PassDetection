import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ROUTES } from "@/constants/routes";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import { ecrCheckerApi } from "../api/ecr-checker.api";
import { ecrKeys, useEcrBatch, useEcrBatches } from "./use-ecr-checker";
import {
  clearEcrUpload, createEcrUploadEntries, ecrErrorMessage, restoreEcrUpload,
  storeEcrUpload, uploadEcrEntries, type EcrUploadEntry, type EcrUploadProgress,
} from "../services/ecr-upload";

export function useEcrWorkspace(initialBatchId: string | null) {
  const [batchId, setBatchId] = useState(initialBatchId);
  const [title, setTitle] = useState("");
  const [entries, setEntries] = useState<EcrUploadEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<"retry" | "export" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<EcrUploadProgress | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const queryClient = useQueryClient();
  const batches = useEcrBatches();
  const batch = useEcrBatch(batchId);

  useEffect(() => () => controllerRef.current?.abort(), []);
  useEffect(() => {
    if (!busy) return;
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [busy]);

  function selectBatch(id: string | null) {
    if (controllerRef.current) return;
    setBatchId(id);
    setEntries([]);
    setProgress(null);
    setError(null);
    setTitle("");
    window.history.replaceState(null, "", `${ROUTES.dashboard.ecrChecker}${id ? `?batch=${encodeURIComponent(id)}` : ""}`);
  }

  function chooseFiles(files: File[]) {
    try {
      const selection = batchId ? restoreEcrUpload(batchId, files) : createEcrUploadEntries(files);
      setEntries(selection);
      setError(null);
      setProgress(null);
    } catch (failure) {
      setEntries([]);
      setError(ecrErrorMessage(failure));
    }
  }

  async function start() {
    if (controllerRef.current) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setBusy(true);
    setError(null);
    let activeId = batchId;
    try {
      let current;
      if (activeId) current = await ecrCheckerApi.get(activeId, controller.signal);
      else {
        if (!entries.length) throw new Error("Choose your passport back-page images first.");
        current = await ecrCheckerApi.create(title.trim() || `ECR check ${new Date().toLocaleDateString("en-GB")}`, entries.length, controller.signal);
        activeId = current.batch_id;
        storeEcrUpload(activeId, entries);
        setBatchId(activeId);
        window.history.replaceState(null, "", `${ROUTES.dashboard.ecrChecker}?batch=${encodeURIComponent(activeId)}`);
      }
      queryClient.setQueryData(ecrKeys.batch(activeId), current);
      if (current.status === "uploading" && current.total_count < current.expected_count) {
        if (!entries.length) throw new Error("Choose the same original images again to resume this upload.");
        await uploadEcrEntries({
          entries,
          existingItems: current.items,
          signal: controller.signal,
          onProgress: setProgress,
          uploadChunk: (chunk, report) => ecrCheckerApi.upload(activeId!, chunk, report, controller.signal),
        });
      }
      const started = await ecrCheckerApi.start(activeId, controller.signal);
      queryClient.setQueryData(ecrKeys.batch(activeId), started);
      clearEcrUpload(activeId);
      setEntries([]);
      setProgress(null);
    } catch (failure) {
      if (!controller.signal.aborted) setError(ecrErrorMessage(failure));
    } finally {
      controllerRef.current = null;
      if (!controller.signal.aborted) {
        setBusy(false);
        void queryClient.invalidateQueries({ queryKey: ecrKeys.all });
      }
    }
  }

  async function performAction(kind: "retry" | "export") {
    if (!batchId || action) return;
    setAction(kind);
    setError(null);
    try {
      if (kind === "retry") {
        const updated = await ecrCheckerApi.retry(batchId);
        queryClient.setQueryData(ecrKeys.batch(batchId), updated);
        void queryClient.invalidateQueries({ queryKey: ecrKeys.batches });
      } else await ecrCheckerApi.export(batchId);
    } catch (failure) {
      if (!isDownloadCancelled(failure)) setError(ecrErrorMessage(failure));
    } finally {
      setAction(null);
    }
  }

  return {
    batchId, title, setTitle, entries, busy, action, error, progress,
    batches, batch, selectBatch, chooseFiles, start, performAction,
  };
}
