import { Pencil } from "lucide-react";

export function PassportDisplayNameAction({ canEdit, selectedIds, onEdit }: {
  canEdit: boolean; selectedIds: string[]; onEdit: (id: string) => void;
}) {
  if (!canEdit || selectedIds.length !== 1) return null;
  return <button type="button"
    className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50"
    onClick={() => onEdit(selectedIds[0])}>
    <Pencil className="h-4 w-4 text-blue-600" />
    Edit display name
  </button>;
}
