"use client";

import { type FormEvent, useId, useRef, useState } from "react";
import { Button, Input } from "@/components/ui";
import type { CreateWhatsAppGroupFromSourceInput } from "../api/whatsapp-source-groups.api";
import { useWhatsAppSourceGroupPreview, useWhatsAppSourceGroups } from "../hooks/use-whatsapp-source-groups";
import { ContactEditor, ErrorBanner, type ManualContact, readErrorMessage } from "./whatsapp-dialog-ui";
import { SourceGroupContactPreview } from "./whatsapp-source-group-preview";

export function SourceGroupBroadcastForm({ isLoading, onClose, onSubmit }: {
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateWhatsAppGroupFromSourceInput) => Promise<void>;
}) {
  const pickerId = useId();
  const [sourceGroupId, setSourceGroupId] = useState("");
  const [name, setName] = useState("");
  const [support, setSupport] = useState<ManualContact>({ name: "", phone_number: "" });
  const [supportContacts, setSupportContacts] = useState<ManualContact[]>([]);
  const [confirmedRevision, setConfirmedRevision] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submitInFlightRef = useRef(false);
  const groups = useWhatsAppSourceGroups();
  const previewQuery = useWhatsAppSourceGroupPreview(sourceGroupId);
  const selectedGroup = groups.data?.find((group) => group.id === sourceGroupId);
  const preview = selectedGroup && !groups.isError && !previewQuery.isError
    && previewQuery.data?.source_group_id === sourceGroupId ? previewQuery.data : undefined;
  const previewReady = Boolean(preview && !previewQuery.isFetching && (preview.contacts?.length ?? preview.recipient_count) > 0);
  const optedIn = Boolean(preview && confirmedRevision === preview.preview_revision);

  function refreshPreview() {
    setConfirmedRevision(null);
    setError(null);
    void previewQuery.refetch();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isLoading || submitInFlightRef.current) return;
    setError(null);
    if (!previewReady || !preview) {
      setError("Choose a group and wait for its contact preview before saving.");
      return;
    }
    if (!name.trim()) {
      setError("Enter a group name.");
      return;
    }
    if (supportContacts.length === 0) {
      setError("Add at least one customer support contact.");
      return;
    }
    if (!optedIn) {
      setError("Confirm that recipients agreed to receive trip updates on WhatsApp.");
      return;
    }
    submitInFlightRef.current = true;
    try {
      await onSubmit({ sourceGroupId, name: name.trim(), supportContacts, recipientOptInConfirmed: true, previewRevision: preview.preview_revision });
    } catch (submitError) {
      const message = readErrorMessage(submitError, "Could not create the broadcast from this group.");
      if ((submitError as { response?: { status?: number } } | null)?.response?.status === 409
        && message === "The source group changed. Refresh its preview and confirm the recipients again.") {
        setConfirmedRevision(null);
        setError("This group changed after your preview. Review the refreshed contacts and confirm recipient opt-in again before saving.");
        void previewQuery.refetch();
      } else {
        setError(message);
      }
    } finally {
      submitInFlightRef.current = false;
    }
  }

  return (
    <form className="mt-5" onSubmit={handleSubmit}>
      <fieldset disabled={isLoading} className="min-w-0 space-y-5">
        <div className="space-y-2">
          <label htmlFor={pickerId} className="block text-sm font-medium text-slate-700">Existing group</label>
          <select
            id={pickerId} value={sourceGroupId} required
            disabled={groups.isPending || groups.isError || !groups.data?.length}
            className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-400"
            onChange={(event) => {
              const group = groups.data?.find((item) => item.id === event.target.value);
              setSourceGroupId(group?.id ?? "");
              setName(group?.name.slice(0, 100) ?? "");
              setConfirmedRevision(null);
              setError(null);
            }}
          >
            <option value="">Select an existing group</option>
            {groups.data?.map((group) => <option key={group.id} value={group.id}>{group.name}{group.import_only ? " · Import only" : ""} ({group.submission_count} submissions)</option>)}
          </select>
          <p className="text-xs text-slate-500">Active groups you have access to are shown here.</p>
          {groups.isPending && <p role="status" className="text-sm text-slate-500">Loading available groups…</p>}
          {groups.isError && <div className="space-y-2"><ErrorBanner message={readErrorMessage(groups.error, "Could not load available groups.")} /><Button type="button" variant="secondary" onClick={() => void groups.refetch()} isLoading={groups.isFetching}>Retry groups</Button></div>}
          {groups.isSuccess && groups.data.length === 0 && <p className="rounded-lg border border-slate-200 p-4 text-sm text-slate-600">No active groups available. Create a group with traveller submissions first, or enter contacts and upload Excel instead.</p>}
        </div>

        {sourceGroupId && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-slate-900">Contact preview</h3>
              <Button type="button" variant="secondary" onClick={refreshPreview} disabled={previewQuery.isFetching}>Refresh preview</Button>
            </div>
            {previewQuery.isFetching ? <p role="status" className="text-sm text-slate-500">Loading contact preview…</p>
              : previewQuery.isError ? <ErrorBanner message={readErrorMessage(previewQuery.error, "Could not load this group’s contacts. Refresh the preview to try again.")} />
              : preview ? <SourceGroupContactPreview preview={preview} />
              : !selectedGroup && !groups.isPending && <ErrorBanner message="This group is no longer available. Choose another group." />}
          </div>
        )}

        <Input label="Group name" hint="Prefilled from the selected group. You can change the broadcast name." value={name} onChange={(event) => setName(event.target.value)} maxLength={100} required />

        <ContactEditor
          title="Passport-link support contacts"
          description="These contacts appear only at the end of the Passport Link message. Welcome messages do not include them."
          value={support} contacts={supportContacts} onValueChange={setSupport}
          onAdd={() => {
            setError(null);
            if (supportContacts.length >= 3) { setError("You can add up to three customer support contacts."); return; }
            if (!support.name.trim() || !support.phone_number.trim()) { setError("Enter both the support contact name and WhatsApp number."); return; }
            setSupportContacts((current) => [...current, { name: support.name.trim(), phone_number: support.phone_number.trim() }]);
            setSupport({ name: "", phone_number: "" });
          }}
          onRemove={(index) => setSupportContacts((current) => current.filter((_, itemIndex) => itemIndex !== index))}
        />

        {previewReady && (
          <label className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 text-sm text-slate-700">
            <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 accent-blue-600" checked={optedIn} onChange={(event) => setConfirmedRevision(event.target.checked ? preview!.preview_revision : null)} />
            <span>I confirm these recipients agreed to receive trip-related WhatsApp updates and can request that messages stop.</span>
          </label>
        )}
        {error && <ErrorBanner message={error} />}
        <div className="flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" isLoading={isLoading} disabled={!previewReady}>Save List</Button>
        </div>
      </fieldset>
    </form>
  );
}
