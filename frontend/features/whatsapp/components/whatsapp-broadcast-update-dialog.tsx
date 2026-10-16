"use client";

import { useId, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { WhatsAppBroadcastGroup } from "../api/whatsapp.api";
import { useWhatsAppGroup } from "../hooks/use-whatsapp";
import { GroupUpdateDialog } from "./group-update-dialog";

export function BroadcastUpdateDialog({ group, onClose }: {
  group: WhatsAppBroadcastGroup; onClose: () => void;
}) {
  const detail = useWhatsAppGroup(group.id);
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [confirmedGroupId, setConfirmedGroupId] = useState("");
  const titleId = useId();
  const selectId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const groups = (detail.data?.linked_client_groups ?? []).filter(item => !["archived", "deleted"].includes(item.status));
  const linkedGroup = groups.find(item => item.id === confirmedGroupId) ?? (groups.length === 1 ? groups[0] : undefined);
  const archived = group.is_archived || detail.data?.is_archived;
  const canOpen = Boolean(linkedGroup && !archived && !detail.isError);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: !canOpen, canClose: true, onClose });

  if (canOpen && linkedGroup) return <GroupUpdateDialog key={linkedGroup.id} groupId={linkedGroup.id} groupName={group.name} broadcastGroupId={group.id} onClose={onClose} />;

  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/55 p-4">
    <div ref={dialogRef} onKeyDown={handleKeyDown} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-2xl">
      <div className="flex items-start justify-between gap-4"><h2 id={titleId} className="text-xl font-semibold">Send update — {group.name}</h2><button type="button" aria-label="Close update preview" onClick={onClose} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button></div>
      {detail.isLoading ? <p role="status" className="mt-5 text-sm text-slate-600">Loading the linked group…</p>
        : detail.isError ? <div role="alert" className="mt-5 space-y-3"><p>Could not load this broadcast’s linked groups.</p><Button variant="secondary" onClick={() => { void detail.refetch(); }}>Try again</Button></div>
        : archived ? <p className="mt-5 text-sm text-slate-600">Restore this broadcast before sending updates.</p>
        : groups.length === 0 ? <p className="mt-5 text-sm text-slate-600">Link this broadcast to a group in All Groups first. The linked group supplies submission and document status for the update preview.</p>
        : <div className="mt-5 space-y-4"><p className="text-sm text-slate-600">Choose the linked group whose submission and document status should be used.</p><label htmlFor={selectId} className="block text-sm font-medium">Group for update filters</label><select id={selectId} value={selectedGroupId} onChange={event => setSelectedGroupId(event.target.value)} className="w-full rounded-lg border border-slate-300 p-3"><option value="">Choose a group</option>{groups.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><Button disabled={!groups.some(item => item.id === selectedGroupId)} onClick={() => setConfirmedGroupId(selectedGroupId)}>Continue to preview</Button></div>}
      <div className="mt-6 flex justify-end"><Button variant="secondary" onClick={onClose}>Cancel</Button></div>
    </div>
  </div>;
}
