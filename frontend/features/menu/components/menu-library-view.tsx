import { Check, X } from "lucide-react";
import { Card, CardContent, ConfirmDialog } from "@/components/ui";
import { cn } from "@/lib/utils/cn";
import type { useMenuLibraryController } from "../hooks/use-menu-library-controller";
import { MenuCategoryRail } from "./menu-category-rail";
import { MenuCategoryWorkspace } from "./menu-category-workspace";

export function MenuLibraryView({ model }: { model: ReturnType<typeof useMenuLibraryController> }) {
  const {
    deleteTarget,
    setDeleteTarget,
    feedback,
    deleteCategory,
    deleteDish,
    confirmDelete,
  } = model;
  return (
    <section className="space-y-5" aria-labelledby="dish-library-title">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
          Step 1
        </p>
        <h2
          id="dish-library-title"
          className="mt-1 text-base font-semibold text-slate-900"
        >
          Build your dish library
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Pick a category on the left, then manage only its dishes on the right.
        </p>
      </div>

      {feedback && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
            feedback.kind === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700",
          )}
          role={feedback.kind === "error" ? "alert" : "status"}
        >
          {feedback.kind === "success" ? (
            <Check className="h-4 w-4 shrink-0" aria-hidden="true" />
          ) : (
            <X className="h-4 w-4 shrink-0" aria-hidden="true" />
          )}
          {feedback.message}
        </div>
      )}

      <Card className="overflow-hidden">
        <CardContent className="p-0">
          <div className="grid min-h-[520px] md:grid-cols-[230px_minmax(0,1fr)]">
            <MenuCategoryRail model={model} />

            <MenuCategoryWorkspace model={model} />
          </div>
        </CardContent>
      </Card>

      <ConfirmDialog
        isOpen={deleteTarget !== null}
        title={
          deleteTarget?.kind === "category" ? "Delete category?" : "Delete dish?"
        }
        description={
          deleteTarget?.kind === "category"
            ? `${deleteTarget.name} and its ${deleteTarget.dishCount} dish${
                deleteTarget.dishCount === 1 ? "" : "es"
              } will be removed. Existing saved plans will keep their meal names.`
            : `${deleteTarget?.name ?? "This dish"} will be removed from the library. Existing saved plans will keep its name.`
        }
        confirmLabel="Delete"
        variant="danger"
        isLoading={deleteCategory.isPending || deleteDish.isPending}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleteTarget(null)}
      />
    </section>
  );
}
