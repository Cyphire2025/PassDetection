import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ContactEditor } from "./whatsapp-dialog-ui";

it("bounds editable contact rows while preserving full-list edit and remove identities", () => {
  const contacts = Array.from({ length: 120 }, (_, index) => ({ name: `Person ${index + 1}`, phone_number: `+919000${String(index).padStart(6, "0")}` }));
  const change = vi.fn();
  const remove = vi.fn();
  render(<ContactEditor title="Recipients" description="Synthetic contact list" value={{ name: "", phone_number: "" }}
    contacts={contacts} onValueChange={vi.fn()} onAdd={vi.fn()} onRemove={remove} onContactChange={change} />);
  expect(screen.getAllByRole("textbox").length).toBeLessThanOrEqual(102);
  const pages = within(screen.getByRole("navigation", { name: "Recipients pagination" }));
  fireEvent.click(pages.getByRole("button", { name: "Next" }));
  expect(screen.queryByLabelText("Recipient 1 name")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Recipient 51 name"), { target: { value: "Reviewed person" } });
  expect(change).toHaveBeenCalledExactlyOnceWith(50, { ...contacts[50], name: "Reviewed person" });
  fireEvent.click(screen.getByRole("button", { name: "Remove Person 51" }));
  expect(remove).toHaveBeenCalledExactlyOnceWith(50);
  fireEvent.click(pages.getByRole("button", { name: "Next" }));
  expect(screen.getByLabelText("Recipient 120 name")).toBeInTheDocument();
  expect(screen.getAllByRole("textbox")).toHaveLength(42);
  expect(contacts).toHaveLength(120);
});
