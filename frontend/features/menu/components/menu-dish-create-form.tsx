import { Plus } from "lucide-react";
import { Button, Input } from "@/components/ui";
import type { useMenuLibraryController } from "../hooks/use-menu-library-controller";
import type { MenuCategory } from "../api/menu.api";

export function MenuDishCreateForm({ model, category: selectedCategory }: { model: ReturnType<typeof useMenuLibraryController>; category: MenuCategory }) {
  const {
    newDishName,
    newDishNotes,
    setOpenDishForm,
    setNewDishName,
    setNewDishNotes,
    createDish,
    submitDish,
  } = model;
  return (
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
  );
}
