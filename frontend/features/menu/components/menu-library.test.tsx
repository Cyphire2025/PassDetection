import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { MenuCategory } from "../api/menu.api";
import { MenuLibrary } from "./menu-library";

const actions = vi.hoisted(() => ({
  createCategory: vi.fn(), updateCategory: vi.fn(), deleteCategory: vi.fn(),
  createDish: vi.fn(), updateDish: vi.fn(), deleteDish: vi.fn(),
}));
vi.mock("../hooks/use-menu", () => ({
  useCreateMenuCategory: () => ({ mutateAsync: actions.createCategory, isPending: false }),
  useUpdateMenuCategory: () => ({ mutateAsync: actions.updateCategory, isPending: false }),
  useDeleteMenuCategory: () => ({ mutateAsync: actions.deleteCategory, isPending: false }),
  useCreateMenuDish: () => ({ mutateAsync: actions.createDish, isPending: false }),
  useUpdateMenuDish: () => ({ mutateAsync: actions.updateDish, isPending: false }),
  useDeleteMenuDish: () => ({ mutateAsync: actions.deleteDish, isPending: false }),
}));
const categories: MenuCategory[] = ["Chicken", "Paneer"].map((name, index) => ({
  id: `category-${index}`, name, sort_order: index, dish_count: 1, active_dish_count: 1,
  created_at: "2026-10-31", updated_at: "category-revision",
  dishes: [{ id: `dish-${index}`, category_id: `category-${index}`, name: `${name} dish`, notes: "Mild",
    is_active: true, sort_order: 0, created_at: "2026-10-31", updated_at: "dish-revision" }],
}));
beforeEach(() => {
  for (const action of Object.values(actions)) action.mockReset().mockResolvedValue(categories[0]);
});
function select(name: string) {
  fireEvent.click(within(screen.getByRole("navigation", { name: "Dish categories" })).getByRole("button", { name: new RegExp(name) }));
}
function submit(name: string) {
  fireEvent.submit(screen.getByRole("textbox", { name }).closest("form")!);
}

it("adds trimmed categories and dishes without altering optional notes semantics", async () => {
  render(<MenuLibrary categories={categories} />);
  fireEvent.change(screen.getByRole("textbox", { name: "New category name" }), { target: { value: "  New category  " } });
  submit("New category name");
  await waitFor(() => expect(actions.createCategory).toHaveBeenCalledExactlyOnceWith("New category"));
  expect(screen.getByRole("textbox", { name: "New category name" })).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "Add dish" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Dish name" }), { target: { value: "  New dish  " } });
  submit("Dish name");
  await waitFor(() => expect(actions.createDish).toHaveBeenCalledExactlyOnceWith({ categoryId: "category-0", name: "New dish", notes: null }));
  await waitFor(() => expect(screen.queryByRole("textbox", { name: "Dish name" })).not.toBeInTheDocument());
});

it("retains category/dish editing and explicit status toggles", async () => {
  render(<MenuLibrary categories={categories} />);
  fireEvent.click(screen.getByRole("button", { name: "Rename Chicken" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Edit category name" }), { target: { value: "  Updated Chicken  " } });
  submit("Edit category name");
  await waitFor(() => expect(actions.updateCategory).toHaveBeenCalledWith({ categoryId: "category-0", name: "Updated Chicken" }));
  fireEvent.click(screen.getByRole("button", { name: "Edit Chicken dish" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Dish name" }), { target: { value: "  Updated dish  " } });
  submit("Dish name");
  await waitFor(() => expect(actions.updateDish).toHaveBeenCalledWith({ dishId: "dish-0", name: "Updated dish", notes: "Mild", isActive: true }));
  await waitFor(() => expect(screen.queryByRole("textbox", { name: "Dish name" })).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Pause Chicken dish" }));
  await waitFor(() => expect(actions.updateDish).toHaveBeenLastCalledWith({ dishId: "dish-0", name: "Chicken dish", notes: "Mild", isActive: false }));
});

it("keeps category deletion confirmation and revision errors reviewable before retry", async () => {
  actions.deleteCategory.mockRejectedValueOnce(new Error("Synthetic revision conflict"));
  render(<MenuLibrary categories={categories} />);
  fireEvent.click(screen.getByRole("button", { name: "Delete Chicken" }));
  const dialog = screen.getByRole("dialog", { name: "Delete category?" });
  expect(dialog).toHaveTextContent("Existing saved plans will keep their meal names.");
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  await screen.findByText("Synthetic revision conflict");
  expect(dialog).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(actions.deleteCategory).toHaveBeenCalledTimes(2);
});

it("falls back to an available category when the selected category disappears", () => {
  const view = render(<MenuLibrary categories={categories} />);
  select("Paneer");
  view.rerender(<MenuLibrary categories={[categories[0]]} />);
  expect(screen.getByRole("heading", { name: "Chicken" })).toBeVisible();
});

it("preserves a newly opened category's dish draft when an earlier category request settles", async () => {
  const pending = Promise.withResolvers<void>(); actions.createDish.mockReturnValue(pending.promise);
  render(<MenuLibrary categories={categories} />);
  fireEvent.click(screen.getByRole("button", { name: "Add dish" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Dish name" }), { target: { value: "Chicken kebab" } });
  submit("Dish name");
  select("Paneer");
  fireEvent.click(screen.getByRole("button", { name: "Add dish" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Dish name" }), { target: { value: "Paneer tikka" } });
  await act(async () => pending.resolve());
  expect(screen.getByRole("textbox", { name: "Dish name" })).toHaveValue("Paneer tikka");
});

it("preserves text entered into the same dish form after its previous submission", async () => {
  const pending = Promise.withResolvers<void>(); actions.createDish.mockReturnValue(pending.promise);
  render(<MenuLibrary categories={categories} />);
  fireEvent.click(screen.getByRole("button", { name: "Add dish" }));
  const name = screen.getByRole("textbox", { name: "Dish name" });
  fireEvent.change(name, { target: { value: "First draft" } }); submit("Dish name");
  fireEvent.change(name, { target: { value: "Newer same-category draft" } });
  await act(async () => pending.resolve());
  expect(screen.getByRole("textbox", { name: "Dish name" })).toHaveValue("Newer same-category draft");
});

it("preserves a newer category edit when an earlier category save settles", async () => {
  const pending = Promise.withResolvers<void>(); actions.updateCategory.mockReturnValue(pending.promise);
  render(<MenuLibrary categories={categories} />);
  fireEvent.click(screen.getByRole("button", { name: "Rename Chicken" })); submit("Edit category name");
  select("Paneer"); fireEvent.click(screen.getByRole("button", { name: "Rename Paneer" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Edit category name" }), { target: { value: "Paneer updated" } });
  await act(async () => pending.resolve());
  expect(screen.getByRole("textbox", { name: "Edit category name" })).toHaveValue("Paneer updated");
});

it("preserves a newer dish edit when an earlier dish save settles", async () => {
  const pending = Promise.withResolvers<void>(); actions.updateDish.mockReturnValue(pending.promise);
  render(<MenuLibrary categories={categories} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit Chicken dish" })); submit("Dish name");
  select("Paneer"); fireEvent.click(screen.getByRole("button", { name: "Edit Paneer dish" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Dish name" }), { target: { value: "Paneer updated dish" } });
  await act(async () => pending.resolve());
  expect(screen.getByRole("textbox", { name: "Dish name" })).toHaveValue("Paneer updated dish");
});

it("preserves a newer category name draft and explicit navigation after an earlier create", async () => {
  const pending = Promise.withResolvers<MenuCategory>(); actions.createCategory.mockReturnValue(pending.promise);
  render(<MenuLibrary categories={categories} />);
  const input = screen.getByRole("textbox", { name: "New category name" });
  fireEvent.change(input, { target: { value: "New category A" } }); submit("New category name");
  fireEvent.change(input, { target: { value: "New category B" } }); select("Paneer");
  await act(async () => pending.resolve({ ...categories[0], id: "new-category" }));
  expect(input).toHaveValue("New category B");
  expect(screen.getByRole("heading", { name: "Paneer" })).toBeVisible();
});
