"use client";

import { Bell, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import type { AnnouncementInput, GcAnnouncement } from "../types";
import { formatGcDateTime, gcAppErrorMessage, toApiDateTime, toLocalDateTime } from "../utils";
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";
import { GcSelect } from "./gc-select";

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
  publish: false,
};

interface AnnouncementForm {
  title: string;
  body: string;
  priority: GcAnnouncement["priority"];
  availableFrom: string;
  availableUntil: string;
  publish: boolean;
}

export function AnnouncementsPanel({
  announcements,
  isCreating,
  isUpdating,
  onCreate,
  onUpdate,
  onSetPublished,
  onDelete,
}: {
  announcements: GcAnnouncement[];
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

  const save = async () => {
    setError(null);
    if (!form.title.trim() || !form.body.trim()) {
      setError("Enter an announcement title and message.");
      return;
    }
    const from = toApiDateTime(form.availableFrom);
    const until = toApiDateTime(form.availableUntil);
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
      publish: form.publish,
    };
    try {
      if (editingId) await onUpdate(editingId, body);
      else await onCreate(body);
      setEditingId(null);
      setForm(EMPTY_FORM);
    } catch (saveError) {
      setError(gcAppErrorMessage(saveError, "The announcement could not be saved."));
    }
  };

  return (
    <div className="space-y-4">
      {error && <GcAlert message={error} />}
      <Card>
        <CardContent className="space-y-4 p-5">
          <div><h3 className="font-semibold text-slate-900">{editingId ? "Edit announcement" : "Create group announcement"}</h3><p className="mt-1 text-sm text-slate-500">Draft messages remain hidden. Avoid sensitive passenger or document details in notification text.</p></div>
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Title" value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} required />
            <GcSelect id="announcement-priority" label="Priority" value={form.priority} options={PRIORITY_OPTIONS} onChange={(priority) => setForm((current) => ({ ...current, priority: priority as GcAnnouncement["priority"] }))} />
          </div>
          <label className="flex flex-col gap-1.5 text-sm font-medium text-slate-700">Message<textarea rows={5} value={form.body} onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal focus:outline-none focus:ring-2 focus:ring-blue-600" /></label>
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Available from" type="datetime-local" value={form.availableFrom} onChange={(event) => setForm((current) => ({ ...current, availableFrom: event.target.value }))} />
            <Input label="Available until" type="datetime-local" value={form.availableUntil} onChange={(event) => setForm((current) => ({ ...current, availableUntil: event.target.value }))} />
          </div>
          <label className="flex min-h-11 items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700"><input type="checkbox" checked={form.publish} onChange={(event) => setForm((current) => ({ ...current, publish: event.target.checked }))} />Publish immediately after saving</label>
          <div className="flex justify-end gap-2">
            {editingId && <Button type="button" variant="secondary" onClick={() => { setEditingId(null); setForm(EMPTY_FORM); }} disabled={isUpdating}>Cancel editing</Button>}
            <Button type="button" isLoading={isCreating || isUpdating} onClick={() => void save()}>{editingId ? "Save announcement" : "Create announcement"}</Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-5">
          <div className="flex items-center justify-between"><div><h3 className="font-semibold text-slate-900">Announcements</h3><p className="mt-1 text-sm text-slate-500">Publication updates the group announcement version.</p></div><Badge variant="secondary">{announcements.length}</Badge></div>
          {announcements.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No announcements created.</p> : announcements.map((announcement) => (
            <div key={announcement.id} className="flex flex-col gap-4 rounded-xl border border-slate-200 p-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="flex min-w-0 gap-3"><span className="rounded-lg bg-blue-50 p-2 text-blue-700"><Bell className="h-5 w-5" /></span><div><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-slate-900">{announcement.title}</p><Badge variant={announcement.is_published ? "success" : "outline"}>{announcement.is_published ? "Published" : "Draft"}</Badge><Badge variant={announcement.priority === "emergency" ? "destructive" : announcement.priority === "important" ? "warning" : "default"}>{announcement.priority}</Badge></div><p className="mt-2 whitespace-pre-wrap text-sm text-slate-600">{announcement.body}</p><p className="mt-2 text-xs text-slate-500">v{announcement.version} · Updated {formatGcDateTime(announcement.updated_at)}</p></div></div>
              <div className="flex shrink-0 flex-wrap gap-2"><Button type="button" variant="secondary" size="sm" leftIcon={<Pencil className="h-4 w-4" />} onClick={() => { setEditingId(announcement.id); setForm({ title: announcement.title, body: announcement.body, priority: announcement.priority, availableFrom: toLocalDateTime(announcement.available_from), availableUntil: toLocalDateTime(announcement.available_until), publish: announcement.is_published }); window.scrollTo({ top: 0 }); }}>Edit</Button><Button type="button" variant="secondary" size="sm" isLoading={isUpdating} onClick={() => void onSetPublished(announcement.id, !announcement.is_published).catch((updateError: unknown) => setError(gcAppErrorMessage(updateError, "Publication state was not changed.")))}>{announcement.is_published ? "Unpublish" : "Publish"}</Button><Button type="button" variant="ghost" size="icon" className="text-red-600 hover:bg-red-50" aria-label={`Delete ${announcement.title}`} onClick={() => setDeleteAnnouncement(announcement)}><Trash2 className="h-4 w-4" /></Button></div>
            </div>
          ))}
        </CardContent>
      </Card>

      <GcDialog open={Boolean(deleteAnnouncement)} title="Delete announcement" description={deleteAnnouncement ? `Delete ${deleteAnnouncement.title}? Published clients will receive a removal version.` : undefined} onClose={() => !isUpdating && setDeleteAnnouncement(null)} closeDisabled={isUpdating} size="md" footer={<><Button type="button" variant="secondary" onClick={() => setDeleteAnnouncement(null)} disabled={isUpdating}>Cancel</Button><Button type="button" variant="danger" isLoading={isUpdating} onClick={() => { if (!deleteAnnouncement) return; void onDelete(deleteAnnouncement.id).then(() => setDeleteAnnouncement(null)).catch((deleteError: unknown) => setError(gcAppErrorMessage(deleteError, "The announcement could not be deleted."))); }}>Delete announcement</Button></>}><p className="text-sm text-slate-600">The audit event and version history remain available to authorized staff.</p></GcDialog>
    </div>
  );
}
