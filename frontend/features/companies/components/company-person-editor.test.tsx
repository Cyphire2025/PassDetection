import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyPersonRecord } from "../types/company-people";
import { CompanyPersonEditor } from "./company-person-editor";

vi.mock("../api/company-people.api", () => ({ companyPeopleApi: { update: vi.fn() } }));
const record: CompanyPersonRecord = { id: "person", status: "active", display_name: "A Person", revision: 2, contact_revision: 1, phone_number: null, phone_verified: false, current_document: { id: "document", passport_id: "passport", revision_number: 1, issuing_country: "IND", document_type: "P", fields: { given_names: "A", surname: "Person", passport_number: "A1234567", document_type: "P", place_of_birth: "DELHI" } } };
beforeEach(() => vi.resetAllMocks());

describe("current person editor", () => {
  it("uses the originally opened revision and preserves entered changes after a background record update", async () => {
    vi.mocked(companyPeopleApi.update).mockRejectedValue(new Error("Record changed. Reopen it."));
    const props = { agencyId: "agency", companyId: "company", record, onSaved: vi.fn(), onCancel: vi.fn(), onBusy: vi.fn() };
    const view = render(<CompanyPersonEditor {...props} />);
    fireEvent.change(screen.getByLabelText(/Full name/), { target: { value: "Edited Name" } });
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: "Corrected spelling" } });
    view.rerender(<CompanyPersonEditor {...props} record={{ ...record, revision: 3, display_name: "Newer Name" }} />);
    expect(screen.getByLabelText(/Full name/)).toHaveValue("Edited Name");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("alert");
    expect(companyPeopleApi.update).toHaveBeenCalledExactlyOnceWith("agency", "company", "person", { expected_revision: 2, idempotency_key: expect.any(String), reason: "Corrected spelling", display_name: "Edited Name", phone_number: null });
    expect(props.onSaved).not.toHaveBeenCalled();
  });

  it("includes passport fields only when changed and reports success after the server saves", async () => {
    vi.mocked(companyPeopleApi.update).mockResolvedValue({ ...record, revision: 3 });
    const onSaved = vi.fn();
    render(<CompanyPersonEditor agencyId="agency" companyId="company" record={record} onSaved={onSaved} onCancel={vi.fn()} onBusy={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Surname"), { target: { value: "Corrected" } });
    fireEvent.change(screen.getByLabelText(/Reason for change/), { target: { value: "Reviewed passport image" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(companyPeopleApi.update).toHaveBeenCalledWith("agency", "company", "person", expect.objectContaining({ expected_revision: 2, fields: { given_names: "A", surname: "Corrected", passport_number: "A1234567" } }));
  });
});
