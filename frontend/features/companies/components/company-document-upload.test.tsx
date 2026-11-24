import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyPersonRecord } from "../types/company-people";
import { CompanyDocumentUploadForm } from "./company-document-upload";

vi.mock("../api/company-people.api", () => ({ companyPeopleApi: { upload: vi.fn() } }));
const record: CompanyPersonRecord = { id: "person", status: "active", revision: 5, display_name: "Person", contact_revision: 1, phone_number: null, phone_verified: false, current_document: { id: "version", passport_id: "passport", revision_number: 2, issuing_country: "IND", document_type: "P", fields: { passport_number: "A1234567", surname: "Person", document_type: "P", place_of_birth: "DELHI" } } };
beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:local-document"), revokeObjectURL: vi.fn() }));
});

describe("staff document versions", () => {
  it("preserves a legacy unknown issuer honestly and never offers it for a known issuer", () => {
    const legacy = { ...record, current_document: { ...record.current_document!, issuing_country: "UNK" } };
    const view = render(<CompanyDocumentUploadForm agencyId="agency" companyId="company" record={legacy} onSaved={vi.fn()} onCancel={vi.fn()} onBusy={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Issuing country" })).toHaveValue("UNK");
    expect(screen.getByRole("option", { name: "Not recorded" })).toBeInTheDocument();
    view.unmount();
    render(<CompanyDocumentUploadForm agencyId="agency" companyId="company" record={record} onSaved={vi.fn()} onCancel={vi.fn()} onBusy={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Issuing country" })).toHaveValue("IND");
    expect(screen.queryByRole("option", { name: "Not recorded" })).not.toBeInTheDocument();
  });

  it("uploads only after explicit review, with the opened revision and retained document context", async () => {
    vi.mocked(companyPeopleApi.upload).mockResolvedValue({ ...record, revision: 6 });
    const onSaved = vi.fn();
    const view = render(<CompanyDocumentUploadForm agencyId="agency" companyId="company" record={record} onSaved={onSaved} onCancel={vi.fn()} onBusy={vi.fn()} />);
    const file = new File(["image"], "scan.jpg", { type: "image/jpeg" });
    await userEvent.upload(screen.getByLabelText("New image", { exact: false }), file);
    fireEvent.change(screen.getByLabelText(/Reason for document update/), { target: { value: "Clearer front image" } });
    expect(screen.getByRole("button", { name: "Save document version" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I checked this image/ }));
    expect(screen.getByRole("button", { name: "Save document version" })).toBeEnabled();
    // jsdom does not mark a user-event-populated required file input as valid.
    // The browser scenario covers native file validation; submit checks this handler's contract.
    fireEvent.submit(screen.getByRole("button", { name: "Save document version" }).closest("form")!);
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(companyPeopleApi.upload).toHaveBeenCalledExactlyOnceWith("agency", "company", "person", { expected_revision: 5, idempotency_key: expect.any(String), reason: "Clearer front image", change_kind: "scan", side: "front", issuing_country: "IND", document_type: "P", fields: { passport_number: "A1234567", surname: "Person" } }, file);
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:local-document");
  });

  it("rejects an unsupported file before preview or upload", () => {
    render(<CompanyDocumentUploadForm agencyId="agency" companyId="company" record={record} onSaved={vi.fn()} onCancel={vi.fn()} onBusy={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("New image", { exact: false }), { target: { files: [new File(["data"], "script.svg", { type: "image/svg+xml" })] } });
    expect(screen.getByRole("alert")).toHaveTextContent("JPEG, PNG or WebP");
    expect(screen.getByRole("button", { name: "Save document version" })).toBeDisabled();
    expect(companyPeopleApi.upload).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("retains the opened revision and retry key, invalidating review only after an edit", async () => {
    vi.mocked(companyPeopleApi.upload).mockRejectedValue(new Error("Connection interrupted"));
    const props = { agencyId: "agency", companyId: "company", record, onSaved: vi.fn(), onCancel: vi.fn(), onBusy: vi.fn() };
    const view = render(<CompanyDocumentUploadForm {...props} />);
    await userEvent.upload(screen.getByLabelText("New image", { exact: false }), new File(["image"], "scan.jpg", { type: "image/jpeg" }));
    fireEvent.change(screen.getByLabelText(/Reason for document update/), { target: { value: "Reviewed scan" } });
    const confirm = screen.getByRole("checkbox", { name: /I checked this image/ });
    fireEvent.click(confirm);
    view.rerender(<CompanyDocumentUploadForm {...props} record={{ ...record, revision: 6 }} />);
    const form = screen.getByRole("button", { name: "Save document version" }).closest("form")!;
    fireEvent.submit(form);
    await screen.findByRole("alert");
    fireEvent.submit(form);
    await waitFor(() => expect(companyPeopleApi.upload).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save document version" })).not.toBeDisabled());
    const calls = vi.mocked(companyPeopleApi.upload).mock.calls;
    expect(calls[0]).toEqual(calls[1]);
    expect(calls[0][3].expected_revision).toBe(5);
    fireEvent.change(screen.getByLabelText(/Reason for document update/), { target: { value: "Updated review note" } });
    expect(confirm).not.toBeChecked();
    fireEvent.click(confirm);
    fireEvent.submit(form);
    await waitFor(() => expect(companyPeopleApi.upload).toHaveBeenCalledTimes(3));
    expect(calls[2][3].idempotency_key).not.toBe(calls[0][3].idempotency_key);
  });

  it("admits one submission while saving and releases a replaced local preview", async () => {
    let finish!: (value: CompanyPersonRecord) => void;
    vi.mocked(companyPeopleApi.upload).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const onSaved = vi.fn();
    const onBusy = vi.fn();
    const view = render(<CompanyDocumentUploadForm agencyId="agency" companyId="company" record={record} onSaved={onSaved} onCancel={vi.fn()} onBusy={onBusy} />);
    vi.mocked(URL.createObjectURL).mockReturnValueOnce("blob:first").mockReturnValueOnce("blob:second");
    const input = screen.getByLabelText("New image", { exact: false });
    await userEvent.upload(input, new File(["first"], "first.jpg", { type: "image/jpeg" }));
    await userEvent.upload(input, new File(["second"], "second.jpg", { type: "image/jpeg" }));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:first");
    fireEvent.change(screen.getByLabelText(/Reason for document update/), { target: { value: "Reviewed replacement" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /I checked this image/ }));
    const form = screen.getByRole("button", { name: "Save document version" }).closest("form")!;
    act(() => { fireEvent.submit(form); fireEvent.submit(form); });
    expect(companyPeopleApi.upload).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await act(async () => finish(record));
    expect(onSaved).toHaveBeenCalledOnce();
    expect(onBusy.mock.calls).toEqual([[true], [false]]);
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:second");
  });
});
