import { UtensilsCrossed } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import type { useMenuLibraryController } from "../hooks/use-menu-library-controller";
import { MenuCategoryHeader } from "./menu-category-header";
import { MenuDishCreateForm } from "./menu-dish-create-form";
import { MenuLibraryDishRow } from "./menu-library-dish-row";

export function MenuCategoryWorkspace({ model }: { model: ReturnType<typeof useMenuLibraryController> }) {
  const {
    openDishForm,
    selectedCategory,
    openAddDish,
  } = model;
  return (
    <div className="min-w-0 bg-white">
      {selectedCategory ? (
        <>
          <MenuCategoryHeader model={model} category={selectedCategory} />

          <div className="p-4 sm:p-5">
            {openDishForm === selectedCategory.id && (
              <MenuDishCreateForm model={model} category={selectedCategory} />
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
                  <MenuLibraryDishRow key={dish.id} model={model} dish={dish} />
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
  );
}
