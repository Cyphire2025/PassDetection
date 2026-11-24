import { useEffect, useRef, useState } from "react";
import { returningApi } from "../api/returning.api";
import { returningDraftApi } from "../api/returning-draft.api";
import { queuedPrivatePreview } from "../services/private-preview-queue";

export function useTravellerDocumentPreview(id: string, draftId: string | undefined, temporary: boolean, available: boolean) {
  const frame = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  const [asset, setAsset] = useState<{ url: string; type: string }>();
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!frame.current) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: "300px" });
    observer.observe(frame.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible || !available) return;
    const controller = new AbortController();
    let url: string | undefined;
    void queuedPrivatePreview(() => temporary && draftId ? returningDraftApi.document(id, draftId, controller.signal) : returningApi.document(id, controller.signal), controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      if (!blob.size || blob.size > 20 * 1024 * 1024 || !["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(blob.type)) throw new Error("Unsupported preview");
      url = URL.createObjectURL(blob);
      setAsset({ url, type: blob.type });
    }).catch(() => {
      if (!controller.signal.aborted) setError(true);
    });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, draftId, temporary, visible, available, attempt]);
  const retry = () => {
    setError(false);
    setAsset(undefined);
    setAttempt((value) => value + 1);
  };
  return { frame, asset, error, retry, setError };
}
