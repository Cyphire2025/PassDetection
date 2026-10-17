"use client";

import { useRef, useState } from "react";
import { ImageUploadField } from "@/features/branding/components/image-upload-field";
import { invalidateBrandingImages, saveBrandingImage, type ImageDraft } from "@/features/branding/api/branding-images.api";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { canAccessApplicationPath } from "@/features/auth/config/route-capabilities";
import { ROUTES } from "@/constants/routes";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { CompanyError, companyErrorMessage } from "@/features/companies/components/company-feedback";
import { GroupCompanyAssignment } from "@/features/companies/components/group-company-assignment";
import { CompanyReassignmentDialog } from "@/features/companies/components/company-reassignment-dialog";
import { refreshGroupAssignment } from "@/features/companies/utils/group-assignment-cache";
import type { CompanyReference } from "@/features/companies/types";
import { uploadLinksApi, type UploadLinkResponse } from "../api/upload-links.api";
import { useUpdateUploadLink } from "../hooks/use-upload-links";
import { getImportOnlySettings } from "../schemas/upload-link.schema";
import { getUploadLinkSettings, getUploadLinkSettingsError, UploadLinkSettings } from "./upload-link-settings";

export function EditGroupDialog({ group, onClose }: { group: UploadLinkResponse; onClose: () => void }) {
  const client = useQueryClient();
  const user = useAuthStore(selectUser);
  const sessionVersion = useAuthStore((state) => state.sessionVersion);
  const [saved, setSaved] = useState(group);
  const [name, setName] = useState(group.name);
  const [settings, setSettings] = useState(() => group.import_only ? getImportOnlySettings() : getUploadLinkSettings(group));
  const [selected, setSelected] = useState<CompanyReference | null>(group.company ?? null);
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState(false);
  const [error, setError] = useState<string>();
  const [banner, setBanner] = useState<ImageDraft>();
  const update = useUpdateUploadLink();
  const inFlight = useRef(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const blocked = busy || review;
  const settingsError = group.import_only ? undefined : getUploadLinkSettingsError(settings);
  const companyChanged = Boolean(selected && selected.id !== saved.company_id);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !blocked, onClose });

  const requireCurrentSession = () => {
    if (useAuthStore.getState().sessionVersion !== sessionVersion) throw new Error("Your session changed. Reopen the group before continuing.");
  };
  const acceptAssignment = async (response: UploadLinkResponse) => {
    requireCurrentSession();
    if (response.id !== group.id || response.agency_id !== group.agency_id) throw new Error("The saved group could not be verified. Refresh and try again.");
    setSaved(response);
    setSelected(response.company ?? null);
    await refreshGroupAssignment(client, response, sessionVersion);
  };
  const saveSettings = async (current: UploadLinkResponse) => {
    requireCurrentSession();
    const changed = name.trim() !== current.name || (!current.import_only &&
      JSON.stringify(settings) !== JSON.stringify(getUploadLinkSettings(current)));
    if (changed) await update.mutateAsync({
      id: current.id, name: name.trim(), destination: current.destination, travel_date: current.travel_date,
      return_date: current.return_date, package_name: current.package_name, timezone: current.timezone,
      ...(current.import_only ? getImportOnlySettings() : settings),
      departure_cities: settings.nearest_international_airport_enabled ? settings.departure_cities : [],
      notes: current.notes,
    });
    requireCurrentSession();
    if (banner !== undefined) {
      const result = await saveBrandingImage("group-banner", current.id, current.agency_id, banner, current.banner_url);
      setSaved((previous) => ({ ...previous, banner_url: result.url }));
      setBanner(undefined);
      await invalidateBrandingImages(client);
      requireCurrentSession();
    }
    onClose();
  };
  const finish = async (assigned?: UploadLinkResponse) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(undefined);
    let assignmentSaved = Boolean(assigned);
    try {
      let current = assigned ?? saved;
      if (assigned) await acceptAssignment(assigned);
      else if (companyChanged && selected) {
        requireCurrentSession();
        current = await uploadLinksApi.assignCompany(saved, selected.id);
        assignmentSaved = true;
        await acceptAssignment(current);
      }
      await saveSettings(current);
    } catch (cause) {
      const message = companyErrorMessage(cause, "The changes could not be saved. Your draft is still here; retry when ready.");
      setError(assignmentSaved ? `Company assignment was saved. ${message}` : message);
    } finally { inFlight.current = false; setBusy(false); }
  };
  const submit = () => {
    if (blocked || inFlight.current || !name.trim() || settingsError) return;
    if (companyChanged && saved.company_id && canAccessApplicationPath(user, ROUTES.dashboard.companies)) {
      setError(undefined);
      setReview(true);
    } else void finish();
  };

  return <>
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="edit-passport-group-title" aria-busy={busy}
      onKeyDown={handleKeyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <form onSubmit={(event) => { event.preventDefault(); submit(); }} className="max-h-[90dvh] w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
          <div><h2 id="edit-passport-group-title" className="text-lg font-semibold text-slate-900">Edit Group</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">{group.import_only ? "Update the name and client company of your Excel import group." : "Update the group name, client company and passport-capture requirements."}</p></div>
          <button type="button" onClick={onClose} disabled={blocked} aria-label="Close edit group dialog" className="rounded-full p-2 text-slate-400 hover:bg-slate-100 disabled:opacity-60"><X className="h-5 w-5" /></button>
        </div>
        <div className="max-h-[calc(90dvh-9rem)] space-y-4 overflow-y-auto px-6 py-5">
          <Input label="Group name" value={name} maxLength={100} required data-dialog-initial-focus disabled={blocked} onChange={(event) => setName(event.target.value)} />
          <GroupCompanyAssignment agencyId={group.agency_id} selected={selected} onChange={setSelected} disabled={blocked} />
          <ImageUploadField kind="banner" value={banner} currentUrl={saved.banner_url} onChange={setBanner} disabled={blocked} />
          {!group.import_only && <UploadLinkSettings value={settings} onChange={(patch) => setSettings((current) => ({ ...current, ...patch }))} disabled={blocked} error={settingsError} />}
          {error && <CompanyError message={error} />}
          {busy && <p role="status" className="text-sm text-slate-600">Saving group changes…</p>}
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={blocked}>Cancel</Button>
          <Button type="submit" isLoading={busy} disabled={blocked || !name.trim() || Boolean(settingsError) || (companyChanged && selected?.status !== "active")}>Save changes</Button>
        </div>
      </form>
    </div>
    {review && selected && <CompanyReassignmentDialog group={saved} target={selected}
      onClose={() => setReview(false)} onSuccess={async (response) => { setReview(false); await finish(response); }} />}
  </>;
}
