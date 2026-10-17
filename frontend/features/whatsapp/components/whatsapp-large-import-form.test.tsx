import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { whatsappApi } from "../api/whatsapp.api";
import { CreateBroadcastDialog } from "./whatsapp-create-broadcast-dialog";

vi.mock("../api/whatsapp.api", () => ({ whatsappApi: { previewContacts: vi.fn() } }));
const preview = { recipient_count: 1, recipients: [{ name: "Delivery contact", phone_number: "+919999999999" }], rejected_count: 699, rejected_counts: { duplicate_phone: 699 }, rejected_rows_truncated: true, omitted_rejected_count: 699, rejected_rows: [] };
function setup() {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><CreateBroadcastDialog isLoading={false} onClose={vi.fn()} onSubmit={onSubmit} /></QueryClientProvider>);
  fireEvent.change(screen.getByRole("textbox", { name: "Group name" }), { target: { value: "Reviewed roster" } });
  const support = within(screen.getByRole("heading", { name: "Passport-link support contacts" }).closest("section")!);
  fireEvent.change(support.getByRole("textbox", { name: "Name" }), { target: { value: "Support" } });
  fireEvent.change(support.getByRole("textbox", { name: "WhatsApp number" }), { target: { value: "+918888888888" } });
  fireEvent.click(support.getByRole("button", { name: "Add" }));
  return { onSubmit, fileInput: view.container.querySelector('input[type="file"]')! };
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(whatsappApi.previewContacts).mockResolvedValue(preview); });
describe("large import form submission", () => {
  it("forwards the original source with the reviewed delivery list on save", async () => {
    const { onSubmit, fileInput } = setup();
    const file = new File(["synthetic"], "roster.xlsx");
    fireEvent.change(fileInput, { target: { files: [file] } });
    await screen.findByText(/original workbook is retained/);
    fireEvent.click(screen.getByRole("checkbox", { name: /recipients agreed/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save List" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ contacts: preview.recipients, duplicateSourceFiles: [file] });
  });
  it("blocks saving a truncated invalid import until it is explicitly discarded", async () => {
    vi.mocked(whatsappApi.previewContacts).mockResolvedValue({ ...preview, rejected_counts: { duplicate_phone: 698, invalid_phone: 1 } });
    const { onSubmit, fileInput } = setup();
    fireEvent.change(fileInput, { target: { files: [new File(["invalid"], "invalid.xlsx")] } });
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Save List" })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Ignore this failed import/ }));
    expect(screen.getByRole("button", { name: "Save List" })).toBeEnabled();
  });
});
