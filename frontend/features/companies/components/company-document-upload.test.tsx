import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
});
