"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import type { AnnouncementInput, GcAnnouncement, GcAppAvailability } from "../types";
import { gcAppErrorMessage, toApiDateTime, toLocalDateTime } from "../utils";
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";
import { GcSelect } from "./gc-select";
import { AnnouncementListItem } from "./announcement-list-item";

const PRIORITY_OPTIONS = [
  { value: "normal", label: "Normal", description: "Standard in-app announcement" },
  { value: "important", label: "Important", description: "Raised visual prominence" },
  { value: "emergency", label: "Emergency", description: "Reserve for urgent operational alerts" },
] as const;

const EMPTY_FORM: AnnouncementForm = {
  title: "",
  body: "",
  priority: "normal",
  availableFrom: "",
  availableUntil: "",
};

interface AnnouncementForm {
  title: string;
  body: string;
  priority: GcAnnouncement["priority"];
  availableFrom: string;
  availableUntil: string;
}

export function AnnouncementsPanel({
  announcements,
  total = announcements.length,
  disabled = false,
  appAvailability,
  isCreating,
  isUpdating,
  onCreate,
  onUpdate,
  onSetPublished,
  onDelete,
}: {
  announcements: GcAnnouncement[];
  total?: number;
  disabled?: boolean;
  appAvailability?: GcAppAvailability;
  isCreating: boolean;
  isUpdating: boolean;
  onCreate: (body: AnnouncementInput) => Promise<void>;
  onUpdate: (announcementId: string, body: AnnouncementInput) => Promise<void>;
  onSetPublished: (announcementId: string, published: boolean) => Promise<void>;
  onDelete: (announcementId: string) => Promise<void>;
}) {
  const [form, setForm] = useState<AnnouncementForm>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteAnnouncement, setDeleteAnnouncement] = useState<GcAnnouncement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const busy = isCreating || isUpdating;
  const hasEdits = Boolean(form.title || form.body || form.availableFrom || form.availableUntil || form.priority !== "normal");
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const save = async (publish: boolean) => {
    if (disabled || busy) return;
    setError(null);
    setSuccess(null);
    if (!form.title.trim() || !form.body.trim()) {
      setError("Enter an announcement title and message.");
      return;
    }
    const from = toApiDateTime(form.availableFrom);
    const until = toApiDateTime(form.availableUntil);
    if ((form.availableFrom && !from) || (form.availableUntil && !until)) {
      setError("Enter valid availability dates or leave them empty.");
      return;
    }
    if (from && until && new Date(until) <= new Date(from)) {
      setError("Announcement expiry must be after its availability start.");
      return;
    }
    const body: AnnouncementInput = {
      title: form.title.trim(),
      body: form.body.trim(),
      priority: form.priority,
      available_from: from,
      available_until: until,
      publish,
    };
    try {
      if (editingId) await onUpdate(editingId, body);
      else await onCreate(body);
      setEditingId(null);
      setForm(EMPTY_FORM);
      setSuccess(publish ? "Announcement published in the app with its availability dates." : "Draft saved. It is hidden from the app.");
    } catch (saveError) {
      setError(gcAppErrorMessage(saveError, "The announcement could not be saved."));
    }
  };

  return (
    <div className="space-y-4">
      {error && <GcAlert message={error} />}
      {success && <GcAlert tone="success" message={success} />}
      {appAvailability && appAvailability !== "active" && <GcAlert tone="info" message="This trip is not currently available to app users. You can prepare announcements here; users also need trip access to see published content." />}
      <Card>
        <CardContent className="p-5"><fieldset disabled={disabled || busy} className="min-w-0 space-y-4">
          <div><h3 className="font-semibold text-slate-900">{editingId ? "Edit announcement" : "Create in-app announcement"}</h3><p className="mt-1 text-sm text-slate-500">Announcements appear inside this trip in the app. Drafts remain hidden. Use Notifications to send a separate phone alert.</p></div>
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Title" value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} required />
            <GcSelect id="announcement-priority" label="Priority" value={form.priority} options={PRIORITY_OPTIONS} onChange={(priority) => setForm((current) => ({ ...current, priority: priority as GcAnnouncement["priority"] }))} />
          </div>
          <label className="flex flex-col gap-1.5 text-sm font-medium text-slate-700">Message<textarea rows={5} value={form.body} onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal focus:outline-none focus:ring-2 focus:ring-blue-600" /></label>
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Available from" type="datetime-local" value={form.availableFrom} onChange={(event) => setForm((current) => ({ ...current, availableFrom: event.target.value }))} />
            <Input label="Available until" type="datetime-local" value={form.availableUntil} onChange={(event) => setForm((current) => ({ ...current, availableUntil: event.target.value }))} />
          </div>
          <p className="text-xs text-slate-500">Dates use your local timezone. A future start schedules app visibility; an expiry ends it. Publishing an announcement does not send a phone alert.</p>
          {editingId && <p className="text-xs text-slate-500">Save draft prepares a hidden new version. The current published version stays visible until you publish its replacement or explicitly unpublish it.</p>}
          <div className="flex justify-end gap-2">
            {(editingId || hasEdits) && <Button type="button" variant="secondary" onClick={() => { setEditingId(null); setForm(EMPTY_FORM); setError(null); }} disabled={isUpdating}>{editingId ? "Cancel editing" : "Discard draft edits"}</Button>}
            <Button type="button" variant="secondary" onClick={() => void save(false)}>Save draft</Button>
            <Button type="button" isLoading={busy} onClick={() => void save(true)}>{form.availableFrom && Date.parse(form.availableFrom) > now ? "Save & schedule" : editingId ? "Save & publish" : "Publish announcement"}</Button>
          </div>
        </fieldset></CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-5">
          <div className="flex items-center justify-between"><div><h3 className="font-semibold text-slate-900">Announcements</h3><p className="mt-1 text-sm text-slate-500">Drafts, scheduled messages, and published announcements for this trip.</p></div><Badge variant="secondary">{total} total</Badge></div>
          {hasEdits && <p className="text-xs text-slate-500">Save or discard your editor changes before changing another announcement.</p>}
          {announcements.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No announcements on this page.</p> : announcements.map((announcement) => (
            <AnnouncementListItem key={announcement.id} announcement={announcement} now={now} disabled={disabled || busy || hasEdits}
              onEdit={() => {
                setEditingId(announcement.id);
                setSuccess(null);
                setForm({ title: announcement.title, body: announcement.body, priority: announcement.priority, availableFrom: toLocalDateTime(announcement.available_from), availableUntil: toLocalDateTime(announcement.available_until) });
                window.scrollTo({ top: 0 });
              }}
              onTogglePublished={() => {
                setError(null);
                void onSetPublished(announcement.id, !announcement.is_published).catch((updateError: unknown) => setError(gcAppErrorMessage(updateError, "Publication state was not changed.")));
              }}
              onDelete={() => setDeleteAnnouncement(announcement)}
            />
          ))}
        </CardContent>
      </Card>

      <GcDialog open={Boolean(deleteAnnouncement)} title="Delete announcement" description={deleteAnnouncement ? `Delete ${deleteAnnouncement.title}? Published clients will receive a removal version.` : undefined} onClose={() => !isUpdating && setDeleteAnnouncement(null)} closeDisabled={isUpdating} size="md" footer={<><Button type="button" variant="secondary" onClick={() => setDeleteAnnouncement(null)} disabled={isUpdating}>Cancel</Button><Button type="button" variant="danger" disabled={disabled} isLoading={isUpdating} onClick={() => { if (!deleteAnnouncement) return; void onDelete(deleteAnnouncement.id).then(() => setDeleteAnnouncement(null)).catch((deleteError: unknown) => setError(gcAppErrorMessage(deleteError, "The announcement could not be deleted."))); }}>Delete announcement</Button></>}><p className="text-sm text-slate-600">The audit event and version history remain available to authorized staff.</p></GcDialog>
    </div>
  );
}
