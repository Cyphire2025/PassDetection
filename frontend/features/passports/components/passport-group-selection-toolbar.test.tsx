import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, it, vi } from "vitest";
import { PassportGroupSelectionToolbar } from "./passport-group-selection-toolbar";

it("keeps selected passengers through search, filters and sort until Clear is used", async () => {
  const resetBulkSelection = vi.fn();
  const setSearch = vi.fn();
  const setPage = vi.fn();
  const props = {
    search: "",
    setSearch,
    setPage,
    isLoading: false,
    isFetching: false,
    sortBy: "name",
    setSortBy: vi.fn(),
    submissionFilter: "all",
    setSubmissionFilter: vi.fn(),
    sortOrder: "asc",
    setSortOrder: vi.fn(),
    selectionPreset: "",
    handleSelectionPreset: vi.fn(),
    customSelectionCount: "",
    selectedPassports: ["selected-outside-current-search"],
    bulkActionsMenuRef: { current: null },
    bulkActionsButtonRef: { current: null },
    isBulkActionsMenuOpen: false,
    setIsBulkActionsMenuOpen: vi.fn(),
    bulkActionsDisclosureId: "bulk-actions",
    resetBulkSelection,
    viewMode: "list",
    setViewMode: vi.fn(),
  } as unknown as ComponentProps<typeof PassportGroupSelectionToolbar>;
  const user = userEvent.setup();
  render(<PassportGroupSelectionToolbar {...props} />);
  await user.type(
    screen.getByRole("textbox", { name: "Search group passengers" }),
    "new person",
  );
  await user.selectOptions(
    screen.getByLabelText("Filter submissions"),
    "needs_review",
  );
  await user.selectOptions(
    screen.getByLabelText("Sort submissions by"),
    "updated_at",
  );
  await user.selectOptions(screen.getByLabelText("Sort direction"), "desc");
  expect(setSearch).toHaveBeenCalled();
  expect(setPage).toHaveBeenCalledWith(1);
  expect(resetBulkSelection).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Clear selection" }));
  expect(resetBulkSelection).toHaveBeenCalledOnce();
});
