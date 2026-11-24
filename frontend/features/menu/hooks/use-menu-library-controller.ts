import { FormEvent, useRef, useState } from "react";
import type { MenuCategory, MenuDish } from "../api/menu.api";
import { useCreateMenuCategory, useCreateMenuDish, useDeleteMenuCategory, useDeleteMenuDish, useUpdateMenuCategory, useUpdateMenuDish } from "./use-menu";
import { menuErrorMessage } from "../utils/menu-errors";
import type { DeleteTarget, Feedback } from "../types/menu-library";

export function useMenuLibraryController(categories: MenuCategory[]) {
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(
    categories[0]?.id ?? null,
  );

  const [newCategoryName, setNewCategoryName] = useState("");

  const categoryNavigationVersion = useRef(0);

  const [newDishDraft, setNewDishDraft] = useState({
    categoryId: null as string | null,
    name: "",
    notes: "",
  });

  const { categoryId: openDishForm, name: newDishName, notes: newDishNotes } = newDishDraft;

  const setOpenDishForm = (categoryId: string | null) =>
    setNewDishDraft(current => ({ ...current, categoryId }));

  const setNewDishName = (name: string) =>
    setNewDishDraft(current => ({ ...current, name }));

  const setNewDishNotes = (notes: string) =>
    setNewDishDraft(current => ({ ...current, notes }));

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
    categoryNavigationVersion.current++;
    setSelectedCategoryId(categoryId);
    setOpenDishForm(null);
    setEditingCategory(null);
    setEditingDish(null);
  };

  const submitCategory = async (event: FormEvent) => {
    event.preventDefault();
    if (!newCategoryName.trim()) return;
    const submittedName = newCategoryName;
    const navigationVersion = categoryNavigationVersion.current;
    setFeedback(null);
    try {
      const category = await createCategory.mutateAsync(newCategoryName.trim());
      setNewCategoryName(current => current === submittedName ? "" : current);
      if (categoryNavigationVersion.current === navigationVersion) {
        setSelectedCategoryId(category.id);
      }
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
    const submittedCategory = editingCategory;
    setFeedback(null);
    try {
      await updateCategory.mutateAsync({
        categoryId: editingCategory.id,
        name: editingCategory.name.trim(),
      });
      setEditingCategory(current => current === submittedCategory ? null : current);
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
    const submittedDraft = newDishDraft;
    setFeedback(null);
    try {
      await createDish.mutateAsync({
        categoryId,
        name: newDishName.trim(),
        notes: newDishNotes.trim() || null,
      });
      setNewDishDraft(current => current === submittedDraft
        ? { categoryId: null, name: "", notes: "" }
        : current);
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
    const submittedDish = editingDish;
    setFeedback(null);
    try {
      await updateDish.mutateAsync({
        dishId: editingDish.id,
        name: editingDish.name.trim(),
        notes: editingDish.notes.trim() || null,
        isActive: editingDish.isActive,
      });
      setEditingDish(current => current === submittedDish ? null : current);
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
    setNewDishDraft({ categoryId, name: "", notes: "" });
    setEditingDish(null);
  };

  return {
    categories,
    newCategoryName,
    setNewCategoryName,
    openDishForm,
    newDishName,
    newDishNotes,
    setOpenDishForm,
    setNewDishName,
    setNewDishNotes,
    editingCategory,
    setEditingCategory,
    editingDish,
    setEditingDish,
    deleteTarget,
    setDeleteTarget,
    feedback,
    createCategory,
    updateCategory,
    deleteCategory,
    createDish,
    updateDish,
    deleteDish,
    selectedCategory,
    selectedCategoryIndex,
    selectCategory,
    submitCategory,
    submitCategoryEdit,
    submitDish,
    submitDishEdit,
    toggleDish,
    confirmDelete,
    openAddDish,
  };
}
