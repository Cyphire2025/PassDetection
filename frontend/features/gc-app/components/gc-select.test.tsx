import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GcDialog } from "./gc-dialog";
import { GcSelect } from "./gc-select";

afterEach(cleanup);
const options = [{ value: "one", label: "First group" }, { value: "two", label: "Second group" }];
it("searches within its owning modal and closes only the popup on Escape", async () => {
  const onClose = vi.fn(), onChange = vi.fn();
  render(<GcDialog open title="Manage groups" onClose={onClose}>
    <GcSelect label="Group" value="" options={options} onChange={onChange} searchable />
  </GcDialog>);
  const trigger = screen.getByRole("combobox", { name: /Group/ });
  fireEvent.click(trigger);
  const search = screen.getByPlaceholderText("Search options");
  await waitFor(() => expect(search).toHaveFocus());
  expect(search.closest("[inert]")).toBeNull();
  fireEvent.change(search, { target: { value: "Second" } });
  expect(screen.queryByRole("option", { name: "First group" })).not.toBeInTheDocument();
  fireEvent.keyDown(search, { key: "Escape" });
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
});

it("keyboard selection returns focus to its trigger and does not choose options still loading", async () => {
  const onChange = vi.fn();
  const view = render(<GcDialog open title="Manage groups" onClose={vi.fn()}>
    <GcSelect label="Group" value="" options={options} onChange={onChange} searchable loading />
  </GcDialog>);
  const trigger = screen.getByRole("combobox", { name: /Group/ });
  fireEvent.click(trigger);
  const search = screen.getByPlaceholderText("Search options");
  await waitFor(() => expect(search).toHaveFocus());
  fireEvent.keyDown(search, { key: "Enter" });
  expect(onChange).not.toHaveBeenCalled();
  view.rerender(<GcDialog open title="Manage groups" onClose={vi.fn()}>
    <GcSelect label="Group" value="" options={options} onChange={onChange} searchable />
  </GcDialog>);
  fireEvent.keyDown(search, { key: "ArrowDown" });
  fireEvent.keyDown(search, { key: "Enter" });
  expect(onChange).toHaveBeenCalledExactlyOnceWith("two");
  expect(trigger).toHaveFocus();
});
