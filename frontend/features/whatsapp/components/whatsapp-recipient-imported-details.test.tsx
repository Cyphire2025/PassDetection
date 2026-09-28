import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RecipientImportedDetails } from "./whatsapp-recipient-imported-details";

const fields = { name: "Annapurna", bdm_code: "25343", email: "old@example.com", phone_number: "+919900000001", source_row: "12", source_file: "contacts.xlsx" };

function openEditor(onSave = vi.fn().mockResolvedValue(undefined)) {
  render(<RecipientImportedDetails name="Annapurna" importedFields={fields} disabled={false} onSave={onSave} />);
  fireEvent.click(screen.getByText("4 imported details"));
  fireEvent.click(screen.getByRole("button", { name: "Edit imported details" }));
  return onSave;
}

it("edits imported values with an original snapshot and leaves the phone and provenance out of the editable fields", async () => {
  const onSave = openEditor();
  fireEvent.change(screen.getByLabelText("Recipient name"), { target: { value: "Annapurna Rao" } });
  fireEvent.change(screen.getByLabelText("Bdm Code"), { target: { value: "25344" } });
  expect(screen.queryByLabelText("Phone Number")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Source Row")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save details" }));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith({ merged_contact_id: null, expected_name: "Annapurna", expected_imported_fields: fields, name: "Annapurna Rao", imported_fields: { bdm_code: "25344", email: "old@example.com" } }));
  await waitFor(() => expect(screen.queryByLabelText("Recipient name")).not.toBeInTheDocument());
});

it("cancels without saving and restores saved values when reopened", () => {
  const onSave = openEditor();
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "unsaved@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onSave).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Edit imported details" }));
  expect(screen.getByLabelText("Email")).toHaveValue("old@example.com");
});

it("keeps edits and exposes the server conflict if saving fails", async () => {
  const onSave = openEditor(vi.fn().mockRejectedValue({ response: { data: { detail: "These details changed. Refresh the recipient list." } } }));
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "draft@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Save details" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Refresh the recipient list"));
  expect(screen.getByLabelText("Email")).toHaveValue("draft@example.com");
  expect(onSave).toHaveBeenCalledTimes(1);
});

it("provides a source-edit instruction for synchronized recipients", () => {
  render(<RecipientImportedDetails name="Source person" importedFields={fields} disabled={false} sourceManaged onSave={vi.fn()} />);
  fireEvent.click(screen.getByText("4 imported details"));
  expect(screen.getByText(/Edit the person's record in that group/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Edit imported details" })).not.toBeInTheDocument();
});

it("edits the chosen saved contact independently for a shared number", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<div><RecipientImportedDetails name="Annapurna" importedFields={fields} disabled={false} onSave={onSave} /><RecipientImportedDetails name="Other" importedFields={{ bdm_code: "987" }} mergedContactId="saved-contact" disabled={false} onSave={onSave} /></div>);
  fireEvent.click(screen.getByText("Other · saved contact details"));
  const contact = screen.getByText("Other · saved contact details").closest("details")!;
  fireEvent.click(within(contact).getByRole("button", { name: "Edit imported details" }));
  fireEvent.change(screen.getByLabelText("Bdm Code"), { target: { value: "988" } });
  fireEvent.click(screen.getByRole("button", { name: "Save details" }));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ merged_contact_id: "saved-contact", expected_name: "Other", imported_fields: { bdm_code: "988" } })));
});

it("prevents repeat saves while a mutation is pending", async () => {
  let finish!: () => void;
  const onSave = openEditor(vi.fn(() => new Promise<void>((resolve) => { finish = resolve; })));
  fireEvent.click(screen.getByRole("button", { name: "Save details" }));
  const editor = screen.getByRole("group", { name: "Edit imported details for Annapurna" });
  expect(within(editor).getByRole("button", { name: "Saving…" })).toBeDisabled();
  expect(within(editor).getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByLabelText("Email")).toBeDisabled();
  expect(onSave).toHaveBeenCalledTimes(1);
  finish();
  await waitFor(() => expect(screen.queryByLabelText("Email")).not.toBeInTheDocument());
});
