import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { WorkspacePagination } from "./workspace-ui";

it("changes the recipient page without submitting its enclosing message form", () => {
  const submit = vi.fn();
  const change = vi.fn();
  render(<form onSubmit={(event) => { event.preventDefault(); submit(); }}>
    <WorkspacePagination total={120} offset={0} limit={50} onChange={change} label="Recipients" />
  </form>);
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(change).toHaveBeenCalledExactlyOnceWith(50);
  expect(submit).not.toHaveBeenCalled();
});

it("keeps a busy recipient page fixed", () => {
  const change = vi.fn();
  render(<WorkspacePagination total={120} offset={50} limit={50} onChange={change} busy label="Recipients" />);
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  expect(change).not.toHaveBeenCalled();
});
