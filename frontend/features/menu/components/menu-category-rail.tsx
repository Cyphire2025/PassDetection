import { ChevronRight, FolderOpen, Plus } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { cn } from "@/lib/utils/cn";
import type { useMenuLibraryController } from "../hooks/use-menu-library-controller";
import { CATEGORY_TONES } from "../types/menu-library";

export function MenuCategoryRail({ model }: { model: ReturnType<typeof useMenuLibraryController> }) {
  const {
    categories,
    newCategoryName,
    setNewCategoryName,
    createCategory,
    selectedCategory,
    selectCategory,
    submitCategory,
  } = model;
  return (
    <aside className="border-b border-slate-200 bg-slate-50/70 md:border-b-0 md:border-r">
      <div className="border-b border-slate-200 px-4 py-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Categories
            </p>
            <p className="mt-0.5 text-[11px] text-slate-400">
              {categories.length} total
            </p>
          </div>
          <FolderOpen className="h-4 w-4 text-slate-400" />
        </div>
      </div>

      {categories.length > 0 ? (
        <nav
          className="max-h-72 space-y-1 overflow-y-auto p-2 md:max-h-[390px]"
          aria-label="Dish categories"
        >
          {categories.map((category, index) => {
            const active = selectedCategory?.id === category.id;
            return (
              <button
                key={category.id}
                type="button"
                onClick={() => selectCategory(category.id)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2.5 text-left transition",
                  active
                    ? "border-blue-200 bg-white shadow-sm"
                    : "border-transparent hover:border-slate-200 hover:bg-white/80",
                )}
                aria-current={active ? "page" : undefined}
              >
                <span
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-xs font-bold uppercase ring-1",
                    CATEGORY_TONES[index % CATEGORY_TONES.length],
                  )}
                >
                  {category.name.charAt(0)}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={cn(
                      "block truncate text-sm font-medium",
                      active ? "text-blue-900" : "text-slate-700",
                    )}
                  >
                    {category.name}
                  </span>
                  <span className="block text-[10px] text-slate-400">
                    {category.active_dish_count} active ·{" "}
                    {category.dish_count} total
                  </span>
                </span>
                <ChevronRight
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    active ? "text-blue-500" : "text-slate-300",
                  )}
                />
              </button>
            );
          })}
        </nav>
      ) : (
        <div className="px-4 py-6 text-center text-xs text-slate-400">
          Add your first category below.
        </div>
      )}

      <form
        onSubmit={submitCategory}
        className="space-y-2 border-t border-slate-200 p-3"
      >
        <Input
          value={newCategoryName}
          onChange={(event) => setNewCategoryName(event.target.value)}
          placeholder="e.g. Chicken"
          aria-label="New category name"
          maxLength={100}
        />
        <Button
          type="submit"
          size="sm"
          className="w-full"
          leftIcon={<Plus className="h-3.5 w-3.5" />}
          disabled={!newCategoryName.trim()}
          isLoading={createCategory.isPending}
        >
          Add category
        </Button>
      </form>
    </aside>
  );
}
