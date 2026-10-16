"use client";

import dynamic from "next/dynamic";
import { Send } from "lucide-react";

const GroupUpdateDialog = dynamic(() => import("@/features/whatsapp/components/group-update-dialog").then(module => module.GroupUpdateDialog));
type Group = {
  group_id: string;
  group_name: string;
  group_status: "active" | "closed" | "archived" | "deleted";
} | null | undefined;

export function GroupUpdatePreview({ open, group, onClose }: { open: boolean; group: Group; onClose: () => void }) {
  return open && group ? <GroupUpdateDialog groupId={group.group_id} groupName={group.group_name} onClose={onClose} /> : null;
}

export function GroupUpdateMenuItem({ groupDetails, includeDeleted, onSelect }: { groupDetails: Group; includeDeleted: boolean; onSelect: () => void }) {
  return <button type="button" role="menuitem" disabled={!groupDetails || includeDeleted || groupDetails.group_status === "archived" || groupDetails.group_status === "deleted"}
    className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50" onClick={onSelect}>
    <Send className="h-4 w-4 text-slate-500" />Send update
  </button>;
}
