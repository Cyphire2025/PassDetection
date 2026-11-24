import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { cn } from "@/lib/utils/cn";
import type { useMenuLibraryController } from "../hooks/use-menu-library-controller";
import { CATEGORY_TONES } from "../types/menu-library";
import type { MenuCategory } from "../api/menu.api";

export function MenuCategoryHeader({ model, category: selectedCategory }: { model: ReturnType<typeof useMenuLibraryController>; category: MenuCategory }) {
  const {
    editingCategory,
    setEditingCategory,
    setDeleteTarget,
    updateCategory,
    selectedCategoryIndex,
    submitCategoryEdit,
    openAddDish,
  } = model;
  return (
    <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="flex min-w-0 items-center gap-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-sm font-bold uppercase ring-1",
            CATEGORY_TONES[
              selectedCategoryIndex % CATEGORY_TONES.length
            ],
          )}
        >
          {selectedCategory.name.charAt(0)}
        </span>
        {editingCategory?.id === selectedCategory.id ? (
          <form
            onSubmit={submitCategoryEdit}
            className="flex min-w-0 items-center gap-2"
          >
            <Input
              value={editingCategory.name}
              onChange={(event) =>
                setEditingCategory({
                  ...editingCategory,
                  name: event.target.value,
                })
              }
              aria-label="Edit category name"
              autoFocus
              className="h-8"
            />
            <Button
              type="submit"
              size="icon"
              className="h-8 w-8"
              aria-label="Save category"
              isLoading={updateCategory.isPending}
            >
              <Check className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              aria-label="Cancel category edit"
              onClick={() => setEditingCategory(null)}
            >
              <X className="h-4 w-4" />
            </Button>
          </form>
        ) : (
          <div className="min-w-0">
            <h3 className="truncate text-lg font-semibold text-slate-900">
              {selectedCategory.name}
            </h3>
            <p className="text-xs text-slate-500">
              {selectedCategory.active_dish_count} active of{" "}
              {selectedCategory.dish_count} dishes
            </p>
          </div>
        )}
      </div>

      {editingCategory?.id !== selectedCategory.id && (
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            leftIcon={<Plus className="h-3.5 w-3.5" />}
            onClick={() => openAddDish(selectedCategory.id)}
          >
            Add dish
          </Button>
          <button
            type="button"
            onClick={() =>
              setEditingCategory({
                id: selectedCategory.id,
                name: selectedCategory.name,
              })
            }
            className="rounded-md p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            aria-label={`Rename ${selectedCategory.name}`}
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() =>
              setDeleteTarget({
                kind: "category",
                id: selectedCategory.id,
                name: selectedCategory.name,
                dishCount: selectedCategory.dish_count,
              })
            }
            className="rounded-md p-2 text-slate-400 transition hover:bg-red-50 hover:text-red-600"
            aria-label={`Delete ${selectedCategory.name}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
