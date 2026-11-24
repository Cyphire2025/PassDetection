"use client";

import { useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { CompanyError, companyErrorMessage } from "@/features/companies/components/company-feedback";
import { invalidateBrandingImages, saveBrandingImage, type ImageDraft } from "../api/branding-images.api";
import { cropBrandingImage, DEFAULT_IMAGE_PLACEMENT } from "../image-crop";
import { ImageUploadField } from "./image-upload-field";
import { useGroupImageAspect } from "./use-group-image-aspect";

export function GroupImageDialog({ kind, groupId, currentUrl, onClose }: {
  kind: "banner" | "background"; groupId: string; currentUrl?: string | null; onClose: () => void;
}) {
  // Freeze the version being edited so polling cannot silently accept a concurrent replacement.
  const [originalUrl] = useState(currentUrl);
  const [draft, setDraft] = useState<ImageDraft>();
  const [placement, setPlacement] = useState(DEFAULT_IMAGE_PLACEMENT);
  const [adjusted, setAdjusted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const client = useQueryClient();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !busy, onClose });
  const aspect = useGroupImageAspect(kind);
  const changed = draft !== undefined || adjusted;

  const save = async () => {
    if (inFlight.current || !changed) return;
    inFlight.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const source = draft ?? (draft === undefined ? originalUrl : null);
      const image = source && adjusted ? await cropBrandingImage(source, aspect, placement) : draft;
      if (image === undefined) return;
      await saveBrandingImage(`group-${kind}`, groupId, undefined, image, originalUrl);
      await invalidateBrandingImages(client);
      onClose();
    } catch (cause) {
      setError(companyErrorMessage(cause, `The ${kind} could not be saved. Please try again.`));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return createPortal(<div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={busy}
    onKeyDown={handleKeyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
    <form className="max-h-[90dvh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-5 shadow-xl sm:p-6"
      onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div><h2 id={titleId} className="text-lg font-semibold text-slate-950">Group {kind}</h2>
          <p className="mt-1 text-sm leading-6 text-slate-500">{kind === "banner" ? "Give this group a destination photo or a trip identity." : "Choose a fixed background for this group workspace."}</p></div>
        <button type="button" aria-label={`Close ${kind} editor`} disabled={busy} onClick={onClose}
          className="rounded-full p-2 text-slate-400 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600">
          <X className="h-5 w-5" aria-hidden="true" /></button>
      </div>
      <ImageUploadField kind={kind} value={draft} currentUrl={originalUrl} disabled={busy}
        onChange={(value) => { setDraft(value); setAdjusted(false); setPlacement(DEFAULT_IMAGE_PLACEMENT); }}
        positioning={{ value: placement, aspect, onChange: (value) => { setPlacement(value); setAdjusted(true); } }} />
      {error && <div className="mt-4"><CompanyError message={error} /></div>}
      <div className="mt-5 flex justify-end gap-2 border-t border-slate-100 pt-4">
        <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
        <Button type="submit" isLoading={busy} disabled={!changed}>Save {kind}</Button>
      </div>
    </form>
  </div>, document.body);
}
