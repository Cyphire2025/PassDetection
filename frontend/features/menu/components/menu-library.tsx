"use client";

import { FormEvent, useState } from "react";
import {
  Check,
  ChevronRight,
  CirclePause,
  FolderOpen,
  Pencil,
  Plus,
  Power,
  Trash2,
  UtensilsCrossed,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  ConfirmDialog,
  Input,
} from "@/components/ui";
import { EmptyState } from "@/components/shared/empty-state";
import { cn } from "@/lib/utils/cn";
import type { MenuCategory, MenuDish } from "../api/menu.api";
import {
  useCreateMenuCategory,
  useCreateMenuDish,
  useDeleteMenuCategory,
  useDeleteMenuDish,
  useUpdateMenuCategory,
  useUpdateMenuDish,
} from "../hooks/use-menu";
import { menuErrorMessage } from "../utils/menu-errors";

type DeleteTarget =
  | { kind: "category"; id: string; name: string; dishCount: number }
  | { kind: "dish"; id: string; name: string };

type Feedback = { kind: "success" | "error"; message: string } | null;

const CATEGORY_TONES = [
  "bg-orange-50 text-orange-700 ring-orange-100",
  "bg-emerald-50 text-emerald-700 ring-emerald-100",
  "bg-blue-50 text-blue-700 ring-blue-100",
  "bg-violet-50 text-violet-700 ring-violet-100",
  "bg-rose-50 text-rose-700 ring-rose-100",
  "bg-cyan-50 text-cyan-700 ring-cyan-100",
];

export function MenuLibrary({ categories }: { categories: MenuCategory[] }) {
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(
    categories[0]?.id ?? null,
  );
  const [newCategoryName, setNewCategoryName] = useState("");
  const [openDishForm, setOpenDishForm] = useState<string | null>(null);
  const [newDishName, setNewDishName] = useState("");
  const [newDishNotes, setNewDishNotes] = useState("");
  const [editingCategory, setEditingCategory] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [editingDish, setEditingDish] = useState<{
    id: string;
    name: string;
    notes: string;
    isActive: boolean;
  } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);

  const createCategory = useCreateMenuCategory();
  const updateCategory = useUpdateMenuCategory();
  const deleteCategory = useDeleteMenuCategory();
  const createDish = useCreateMenuDish();
  const updateDish = useUpdateMenuDish();
  const deleteDish = useDeleteMenuDish();

  const selectedCategory =
    categories.find((category) => category.id === selectedCategoryId) ??
    categories[0] ??
    null;
  const selectedCategoryIndex = Math.max(
    0,
    categories.findIndex((category) => category.id === selectedCategory?.id),
  );

  const selectCategory = (categoryId: string) => {
    setSelectedCategoryId(categoryId);
    setOpenDishForm(null);
    setEditingCategory(null);
    setEditingDish(null);
  };

  const submitCategory = async (event: FormEvent) => {
    event.preventDefault();
    if (!newCategoryName.trim()) return;
    setFeedback(null);
    try {
      const category = await createCategory.mutateAsync(newCategoryName.trim());
      setNewCategoryName("");
      setSelectedCategoryId(category.id);
      setFeedback({ kind: "success", message: "Category added." });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Category could not be added."),
      });
    }
  };

  const submitCategoryEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingCategory?.name.trim()) return;
    setFeedback(null);
    try {
      await updateCategory.mutateAsync({
        categoryId: editingCategory.id,
        name: editingCategory.name.trim(),
      });
      setEditingCategory(null);
      setFeedback({ kind: "success", message: "Category updated." });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Category could not be updated."),
      });
    }
  };

  const submitDish = async (event: FormEvent, categoryId: string) => {
    event.preventDefault();
    if (!newDishName.trim()) return;
    setFeedback(null);
    try {
      await createDish.mutateAsync({
        categoryId,
        name: newDishName.trim(),
        notes: newDishNotes.trim() || null,
      });
      setNewDishName("");
      setNewDishNotes("");
      setOpenDishForm(null);
      setFeedback({ kind: "success", message: "Dish added to the library." });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Dish could not be added."),
      });
    }
  };

  const submitDishEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!editingDish?.name.trim()) return;
    setFeedback(null);
    try {
      await updateDish.mutateAsync({
        dishId: editingDish.id,
        name: editingDish.name.trim(),
        notes: editingDish.notes.trim() || null,
        isActive: editingDish.isActive,
      });
      setEditingDish(null);
      setFeedback({ kind: "success", message: "Dish updated." });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Dish could not be updated."),
      });
    }
  };

  const toggleDish = async (dish: MenuDish) => {
    setFeedback(null);
    try {
      await updateDish.mutateAsync({
        dishId: dish.id,
        name: dish.name,
        notes: dish.notes,
        isActive: !dish.is_active,
      });
      setFeedback({
        kind: "success",
        message: dish.is_active
          ? `${dish.name} paused and will not be planned.`
          : `${dish.name} is active again.`,
      });
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "Dish status could not be changed."),
      });
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setFeedback(null);
    try {
      if (deleteTarget.kind === "category") {
        await deleteCategory.mutateAsync(deleteTarget.id);
        if (selectedCategory?.id === deleteTarget.id) {
          const nextCategory = categories.find(
            (category) => category.id !== deleteTarget.id,
          );
          setSelectedCategoryId(nextCategory?.id ?? null);
        }
        setFeedback({ kind: "success", message: "Category deleted." });
      } else {
        await deleteDish.mutateAsync(deleteTarget.id);
        setFeedback({ kind: "success", message: "Dish deleted." });
      }
      setDeleteTarget(null);
    } catch (error) {
      setFeedback({
        kind: "error",
        message: menuErrorMessage(error, "The item could not be deleted."),
      });
    }
  };

  const openAddDish = (categoryId: string) => {
    setOpenDishForm(categoryId);
    setNewDishName("");
    setNewDishNotes("");
    setEditingDish(null);
  };

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

            <div className="min-w-0 bg-white">
              {selectedCategory ? (
                <>
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

                  <div className="p-4 sm:p-5">
                    {openDishForm === selectedCategory.id && (
                      <form
                        onSubmit={(event) =>
                          void submitDish(event, selectedCategory.id)
                        }
                        className="mb-4 grid gap-3 rounded-xl border border-blue-200 bg-blue-50/50 p-4 lg:grid-cols-2"
                      >
                        <Input
                          value={newDishName}
                          onChange={(event) => setNewDishName(event.target.value)}
                          label="Dish name"
                          placeholder={`Add a ${selectedCategory.name} dish`}
                          autoFocus
                          maxLength={120}
                        />
                        <Input
                          value={newDishNotes}
                          onChange={(event) => setNewDishNotes(event.target.value)}
                          label="Notes (optional)"
                          placeholder="e.g. dry, mild, Jain"
                          maxLength={500}
                        />
                        <div className="flex justify-end gap-2 lg:col-span-2">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => setOpenDishForm(null)}
                          >
                            Cancel
                          </Button>
                          <Button
                            type="submit"
                            size="sm"
                            leftIcon={<Plus className="h-3.5 w-3.5" />}
                            isLoading={createDish.isPending}
                            disabled={!newDishName.trim()}
                          >
                            Add dish
                          </Button>
                        </div>
                      </form>
                    )}

                    {selectedCategory.dishes.length === 0 ? (
                      <EmptyState
                        icon={<UtensilsCrossed className="h-5 w-5" />}
                        title={`No ${selectedCategory.name} dishes yet`}
                        description="Add the dishes your team can serve in this category."
                        action={{
                          label: "Add first dish",
                          onClick: () => openAddDish(selectedCategory.id),
                        }}
                        className="border-dashed bg-slate-50"
                      />
                    ) : (
                      <ul className="space-y-2" role="list">
                        {selectedCategory.dishes.map((dish) => (
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
                        ))}
                      </ul>
                    )}
                  </div>
                </>
              ) : (
                <div className="flex min-h-[520px] items-center justify-center p-6">
                  <EmptyState
                    icon={<UtensilsCrossed className="h-5 w-5" />}
                    title="Start with your first category"
                    description="For example: Chicken, Paneer, Fish, Dal, Chinese, or Desserts."
                    className="w-full max-w-md border-0 shadow-none"
                  />
                </div>
              )}
            </div>
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
