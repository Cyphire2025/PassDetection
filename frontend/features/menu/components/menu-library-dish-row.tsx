import { CirclePause, Pencil, Power, Trash2 } from "lucide-react";
import { Badge, Button, Input } from "@/components/ui";
import { cn } from "@/lib/utils/cn";
import type { useMenuLibraryController } from "../hooks/use-menu-library-controller";
import type { MenuDish } from "../api/menu.api";

export function MenuLibraryDishRow({ model, dish }: { model: ReturnType<typeof useMenuLibraryController>; dish: MenuDish }) {
  const {
    editingDish,
    setEditingDish,
    setDeleteTarget,
    updateDish,
    submitDishEdit,
    toggleDish,
  } = model;
  return (
    <li key={dish.id}>
      {editingDish?.id === dish.id ? (
        <form
          onSubmit={submitDishEdit}
          className="grid gap-3 rounded-xl border border-blue-200 bg-blue-50/50 p-4 lg:grid-cols-2"
        >
          <Input
            value={editingDish.name}
            onChange={(event) =>
              setEditingDish({
                ...editingDish,
                name: event.target.value,
              })
            }
            label="Dish name"
            autoFocus
            maxLength={120}
          />
          <Input
            value={editingDish.notes}
            onChange={(event) =>
              setEditingDish({
                ...editingDish,
                notes: event.target.value,
              })
            }
            label="Notes (optional)"
            placeholder="e.g. mild gravy"
            maxLength={500}
          />
          <div className="flex justify-end gap-2 lg:col-span-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setEditingDish(null)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              isLoading={updateDish.isPending}
              disabled={!editingDish.name.trim()}
            >
              Save dish
            </Button>
          </div>
        </form>
      ) : (
        <div
          className={cn(
            "group flex items-center gap-3 rounded-xl border px-3 py-3 transition sm:px-4",
            dish.is_active
              ? "border-slate-200 bg-white hover:border-blue-200 hover:shadow-sm"
              : "border-slate-100 bg-slate-50 opacity-70",
          )}
        >
          <span
            className={cn(
              "h-2.5 w-2.5 shrink-0 rounded-full",
              dish.is_active
                ? "bg-emerald-500"
                : "bg-slate-300",
            )}
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-sm font-medium text-slate-700">
                {dish.name}
              </p>
              {!dish.is_active && (
                <Badge
                  variant="outline"
                  className="px-1.5 py-0 text-[9px]"
                >
                  Paused
                </Badge>
              )}
            </div>
            {dish.notes && (
              <p className="mt-0.5 truncate text-[11px] text-slate-400">
                {dish.notes}
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center">
            <button
              type="button"
              onClick={() => void toggleDish(dish)}
              className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-50 hover:text-blue-600"
              aria-label={
                dish.is_active
                  ? `Pause ${dish.name}`
                  : `Activate ${dish.name}`
              }
              title={
                dish.is_active
                  ? "Pause from planning"
                  : "Use in planning"
              }
            >
              {dish.is_active ? (
                <CirclePause className="h-3.5 w-3.5" />
              ) : (
                <Power className="h-3.5 w-3.5" />
              )}
            </button>
            <button
              type="button"
              onClick={() =>
                setEditingDish({
                  id: dish.id,
                  name: dish.name,
                  notes: dish.notes ?? "",
                  isActive: dish.is_active,
                })
              }
              className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-50 hover:text-slate-700"
              aria-label={`Edit ${dish.name}`}
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() =>
                setDeleteTarget({
                  kind: "dish",
                  id: dish.id,
                  name: dish.name,
                })
              }
              className="rounded-md p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-600"
              aria-label={`Delete ${dish.name}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
