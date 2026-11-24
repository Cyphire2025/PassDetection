import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CoordinatorMultiSelect } from "./tour-operations-ui";

const coordinators = [{
  id: "coordinator-1", full_name: "Test Coordinator", email: "coordinator@example.test", agency_id: "agency-1",
  is_active: true, assigned_groups_count: 1, assigned_passengers_count: 10,
  last_login_at: null, created_at: "2026-10-30", updated_at: "2026-10-30",
}];

it("preserves selection semantics and disables an already-open menu while saving", () => {
  const onToggle = vi.fn();
  const props = { coordinators, selectedIds: ["coordinator-1"], onToggle };
  const { rerender } = render(<CoordinatorMultiSelect {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "1 coordinator" }));
  const option = screen.getByRole("menuitemcheckbox");
  expect(option).toHaveAttribute("aria-checked", "true");
  fireEvent.click(option);
  expect(onToggle).toHaveBeenCalledExactlyOnceWith("coordinator-1", false);
  rerender(<CoordinatorMultiSelect {...props} disabled />);
  expect(option).toBeDisabled();
  fireEvent.click(option);
  expect(onToggle).toHaveBeenCalledTimes(1);
});
