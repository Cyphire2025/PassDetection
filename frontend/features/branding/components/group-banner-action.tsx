"use client";

import { useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ImagePlus, X } from "lucide-react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { CompanyError, companyErrorMessage } from "@/features/companies/components/company-feedback";
import { invalidateBrandingImages, saveBrandingImage, type ImageDraft } from "../api/branding-images.api";
import { ImageUploadField } from "./image-upload-field";

export function GroupBannerAction({ group, disabled }: { group?: { group_id: string; banner_url?: string | null } | null; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  if (!group || disabled) return null;
  return <>
    <Button type="button" variant="secondary" size="sm" aria-label={group.banner_url ? "Edit banner" : "Add banner"} title={group.banner_url ? "Edit banner" : "Add banner"} onClick={() => setOpen(true)}><ImagePlus className="h-4 w-4" aria-hidden="true" /><span className="hidden sm:inline">{group.banner_url ? "Edit banner" : "Add banner"}</span></Button>
    {open && <GroupBannerDialog groupId={group.group_id} currentUrl={group.banner_url} onClose={() => setOpen(false)} />}
  </>;
}

function GroupBannerDialog({ groupId, currentUrl, onClose }: { groupId: string; currentUrl?: string | null; onClose: () => void }) {
  // Keep this edit tied to the image version that was opened.
  const [originalUrl] = useState(currentUrl);
  const [draft, setDraft] = useState<ImageDraft>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const client = useQueryClient();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !busy, onClose });
  return createPortal(<div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={busy} onKeyDown={handleKeyDown}
    className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
    <form className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-5 shadow-xl sm:p-6" onSubmit={async (event) => {
      event.preventDefault();
      if (inFlight.current || draft === undefined) return;
      inFlight.current = true; setBusy(true); setError(undefined);
      try {
        await saveBrandingImage("group-banner", groupId, undefined, draft, originalUrl);
        await invalidateBrandingImages(client);
        onClose();
      } catch (cause) { setError(companyErrorMessage(cause, "The banner could not be saved. Your current banner is still available; try again.")); }
      finally { inFlight.current = false; setBusy(false); }
    }}>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div><h2 id={titleId} className="text-lg font-semibold text-slate-950">Group banner</h2><p className="mt-1 text-sm leading-6 text-slate-500">Give this group a destination photo or a trip identity.</p></div>
        <button type="button" aria-label="Close banner editor" disabled={busy} onClick={onClose} className="rounded-full p-2 text-slate-400 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"><X className="h-5 w-5" aria-hidden="true" /></button>
      </div>
      <ImageUploadField kind="banner" value={draft} currentUrl={originalUrl} onChange={setDraft} disabled={busy} />
      {error && <div className="mt-4"><CompanyError message={error} /></div>}
      <div className="mt-5 flex justify-end gap-2 border-t border-slate-100 pt-4"><Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button><Button type="submit" isLoading={busy} disabled={draft === undefined}>Save banner</Button></div>
    </form>
  </div>, document.body);
}
