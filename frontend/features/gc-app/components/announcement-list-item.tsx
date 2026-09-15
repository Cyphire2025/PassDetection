import { Bell, Pencil, Trash2 } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { GcAnnouncement } from "../types";
import { formatGcDateTime, gcPublicationState } from "../utils";
import { AnnouncementNotificationStatusPanel } from "./announcement-notification-status";

export function AnnouncementListItem({ announcement, agencyId, groupId, now, disabled, onEdit, onTogglePublished, onDelete }: {
  announcement: GcAnnouncement;
  agencyId: string | null;
  groupId: string;
  now: number;
  disabled: boolean;
  onEdit: () => void;
  onTogglePublished: () => void;
  onDelete: () => void;
}) {
  const publication = gcPublicationState(announcement, now);
  return (
    <article className="space-y-4 rounded-xl border border-slate-200 p-4" aria-label={announcement.title}>
      <div className="flex min-w-0 gap-3">
        <span className="h-fit rounded-lg bg-blue-50 p-2 text-blue-700"><Bell className="h-5 w-5" aria-hidden="true" /></span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-medium text-slate-900">{announcement.title}</h4>
            <Badge variant={publication.variant}>{publication.label}</Badge>
            <Badge variant={announcement.priority === "emergency" ? "destructive" : announcement.priority === "important" ? "warning" : "default"}>{announcement.priority}</Badge>
          </div>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-600">{announcement.body}</p>
          <p className="mt-2 text-xs text-slate-500">Available from {announcement.available_from ? formatGcDateTime(announcement.available_from) : "publication"} · Until {announcement.available_until ? formatGcDateTime(announcement.available_until) : "no expiry"}</p>
          <p className="mt-2 text-xs text-slate-500">v{announcement.version} · Updated {formatGcDateTime(announcement.updated_at)}</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="secondary" size="sm" disabled={disabled} leftIcon={<Pencil className="h-4 w-4" />} onClick={onEdit}>Edit</Button>
        <Button type="button" variant="secondary" size="sm" disabled={disabled} onClick={onTogglePublished}>{announcement.is_published ? "Unpublish" : "Publish"}</Button>
        <Button type="button" variant="danger" size="sm" disabled={disabled} leftIcon={<Trash2 className="h-4 w-4" aria-hidden="true" />} onClick={onDelete}>Delete</Button>
      </div>
      <AnnouncementNotificationStatusPanel agencyId={agencyId} groupId={groupId} announcementId={announcement.id} version={announcement.version} />
    </article>
  );
}
