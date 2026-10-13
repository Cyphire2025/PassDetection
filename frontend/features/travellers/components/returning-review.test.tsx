import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { returningApi } from "../api/returning.api";
import type { ReturningHistory } from "../types";
import { ReturningReview } from "./returning-review";

vi.mock("../api/returning.api", () => ({ returningApi: { complete: vi.fn(), document: vi.fn(), history: vi.fn(), selectPassport: vi.fn(), requestContact: vi.fn(), verifyContact: vi.fn() } }));
const history: ReturningHistory = {
  display_name: "Test Person", contact_phone: "+919999999999", extracted_fields: { surname: "Person", given_names: "Test", passport_number: "A1234567" },
  passport: { id: "passport-a", number: "A1234567", issuing_country: "IND", document_type: "P", date_of_birth: "1990-01-01", issue_date: null, expiry_date: "2030-01-01", revision: 2 },
  documents: [{ id: "front", label: "Passport front", content_type: "image/jpeg", available: true }],
  suitability: { outcome: "review_required", reason_codes: ["DESTINATION_RULE_UNKNOWN"] },
  group_requirements: { custom_questions: [{ id: "meal", label: "Trip meal", enabled: true, required: true, options: ["Veg", "Jain"] }], custom_details: [], require_selfie: false, require_contact_phone: false, current_detail_fields: [{ key: "staff_code", label: "Staff code", required: true, options: [], type: "text" }] },
  missing_requirements: [], question_version: "v2", review_version: "review-v2", participation_revision: 3,
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private-test"), revokeObjectURL: vi.fn() }));
  vi.mocked(returningApi.document).mockResolvedValue(new Blob(["synthetic"], { type: "image/jpeg" }));
});

describe("protected returning review", () => {
  it("sends owned family source proof and refuses a completion response without a bound saved submission", async () => {
    const onCompleted = vi.fn();
    const ownedSource = { source_submission_id: "owned-family-upload", expected_extraction_revision: 3, uploadSessionId: "member-upload-capability" };
    vi.mocked(returningApi.complete).mockResolvedValueOnce({ status: "submitted", participation_id: "participation" }).mockResolvedValueOnce({ status: "accepted", participation_id: "participation", source_submission_id: "saved-reuse-snapshot" });
    render(<ReturningReview history={{ ...history, saved_answers: { custom_answers: { meal: "Veg" }, custom_detail_answers: {}, current_details: { staff_code: "0009" } } }} groupName="Test trip" onFresh={vi.fn()} onReplace={vi.fn()} ownedSource={ownedSource} onCompleted={onCompleted} />);
    fireEvent.click(screen.getByRole("button", { name: /Passport front · Open preview/ }));
    fireEvent.load(await screen.findByRole("img", { name: "Passport front" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the images/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit this trip’s information" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be linked to this upload");
    expect(onCompleted).not.toHaveBeenCalled();
    expect(returningApi.complete).toHaveBeenLastCalledWith(expect.objectContaining({ owned_source: { source_submission_id: "owned-family-upload", expected_extraction_revision: 3 } }), expect.any(AbortSignal), "member-upload-capability");
    fireEvent.click(screen.getByRole("button", { name: "Submit this trip’s information" }));
    await screen.findByRole("heading", { name: "Trip information accepted" });
    expect(onCompleted).toHaveBeenCalledExactlyOnceWith({ status: "accepted", participation_id: "participation", source_submission_id: "saved-reuse-snapshot" });
  });
  it("retains only server-authorized same-trip answers and refreshes a stale review before confirming again", async () => {
    const saved = { ...history, saved_answers: { custom_answers: { meal: "Veg" }, custom_detail_answers: {}, current_details: { staff_code: "0009" } } };
    vi.mocked(returningApi.complete).mockRejectedValueOnce({ status: 409, message: "The trip changed. Refresh the current requirements." });
    vi.mocked(returningApi.history).mockResolvedValue({ ...saved, review_version: "review-v3", question_version: "v3", group_requirements: { ...history.group_requirements, custom_questions: [...history.group_requirements.custom_questions, { id: "seat", label: "New seat preference", enabled: true, required: true, options: ["Window", "Aisle"] }] } });
    render(<ReturningReview history={saved} groupName="Test trip" onFresh={vi.fn()} onReplace={vi.fn()} />);
    expect(screen.getByLabelText(/Staff code/)).toHaveValue("0009");
    expect(screen.getByRole("combobox", { name: /Trip meal/ })).toHaveValue("Veg");
    fireEvent.click(screen.getByRole("button", { name: /Passport front · Open preview/ }));
    fireEvent.load(await screen.findByRole("img", { name: "Passport front" }));
    fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the images/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit this trip’s information" }));
    fireEvent.click(await screen.findByRole("button", { name: "Refresh current trip requirements" }));
    await screen.findByRole("combobox", { name: /New seat preference/ });
    expect(screen.getByRole("combobox", { name: /Trip meal/ })).toHaveValue("Veg");
    expect(screen.getByRole("combobox", { name: /New seat preference/ })).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: /reviewed the images/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Submit this trip’s information" })).toBeDisabled();
    const previousKey = vi.mocked(returningApi.complete).mock.calls[0][0].idempotency_key;
    vi.mocked(returningApi.complete).mockResolvedValue({ status: "submitted", participation_id: "participation" });
    fireEvent.change(screen.getByRole("combobox", { name: /New seat preference/ }), { target: { value: "Window" } });
    fireEvent.click(screen.getByRole("button", { name: /Passport front · Open preview/ }));
    fireEvent.load(await screen.findByRole("img", { name: "Passport front" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the images/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit this trip’s information" }));
    await screen.findByRole("heading", { name: "Trip information submitted" });
    expect(vi.mocked(returningApi.complete).mock.calls[1][0].idempotency_key).not.toBe(previousKey);
    expect(vi.mocked(returningApi.complete).mock.calls[1][0]).toMatchObject({ review_version: "review-v3", question_version: "v3", custom_answers: { meal: "Veg", seat: "Window" } });
  });

  it("selects another accepted passport for this trip and resets image review while retaining unchanged draft answers", async () => {
    const passports = [{ id: "passport-a", number: "A1234567", issuing_country: "IND", document_type: "P", is_default: true, expiry_date: "2030-01-01" }, { id: "passport-b", number: "B1234567", issuing_country: "GBR", document_type: "P", is_default: false, expiry_date: "2031-01-01" }];
    vi.mocked(returningApi.selectPassport).mockResolvedValue({ ...history, passport: { ...history.passport!, id: "passport-b", number: "B1234567" }, available_passports: passports, review_version: "review-b" });
    render(<ReturningReview history={{ ...history, available_passports: passports }} groupName="Test trip" onFresh={vi.fn()} onReplace={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Staff code/), { target: { value: "0009" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the images/ }));
    fireEvent.change(screen.getByLabelText("Passport for this trip"), { target: { value: "passport-b" } });
    await waitFor(() => expect(screen.getByLabelText("Passport for this trip")).toHaveValue("passport-b"));
    expect(returningApi.selectPassport).toHaveBeenCalledWith("passport-b", expect.any(AbortSignal));
    expect(screen.getByLabelText(/Staff code/)).toHaveValue("0009");
    expect(screen.getByRole("checkbox", { name: /reviewed the images/ })).not.toBeChecked();
    expect(returningApi.document).not.toHaveBeenCalled();
  });

  it("loads images only on demand, requires review, sends current answers, and preserves idempotency on a retry", async () => {
    vi.mocked(returningApi.complete).mockRejectedValueOnce(new Error("Temporary failure")).mockResolvedValueOnce({ status: "submitted", participation_id: "participation" });
    render(<ReturningReview history={history} groupName="Test trip" onFresh={vi.fn()} onReplace={vi.fn()} />);
    expect(returningApi.document).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Submit this trip’s information" })).toBeDisabled();
    expect(screen.getByText("Test", { exact: true })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Passport front · Open preview/ }));
    const image = await screen.findByRole("img", { name: "Passport front" });
    fireEvent.load(image);
    fireEvent.click(screen.getByRole("button", { name: "Close preview" }));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-test");
    fireEvent.change(screen.getByLabelText(/Staff code/), { target: { value: "0009" } });
    fireEvent.change(screen.getByRole("combobox", { name: /Trip meal/ }), { target: { value: "Jain" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the images/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit this trip’s information" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Submit this trip’s information" }));
    await screen.findByRole("heading", { name: "Trip information submitted" });
    const calls = vi.mocked(returningApi.complete).mock.calls;
    expect(calls[0][0]).toEqual(calls[1][0]);
    expect(calls[0][0]).toMatchObject({ question_version: "v2", review_version: "review-v2", expected_participation_revision: 3, current_details: { staff_code: "0009" }, custom_answers: { meal: "Jain" }, information_confirmed: true });
    expect(screen.getByText(/travel team will review/)).toBeVisible();
  });

  it("blocks completion when a current required page or live capture is missing", () => {
    const onFresh = vi.fn();
    render(<ReturningReview history={{ ...history, missing_requirements: ["passport_back"] }} groupName="Test trip" onFresh={onFresh} onReplace={vi.fn()} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the images/ }));
    expect(screen.getByRole("button", { name: "Submit this trip’s information" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Upload current documents" }));
    expect(onFresh).toHaveBeenCalledOnce();
    expect(returningApi.complete).not.toHaveBeenCalled();
  });

  it("blocks a saved document the server cannot assess even after the images are reviewed", async () => {
    render(<ReturningReview history={{ ...history, suitability: { outcome: "cannot_assess", reason_codes: ["EXPIRY_DATE_MISSING"] } }} groupName="Test trip" onFresh={vi.fn()} onReplace={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Passport front · Open preview/ }));
    fireEvent.load(await screen.findByRole("img", { name: "Passport front" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the images/ }));
    expect(screen.getByText(/saved passport cannot yet be assessed/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Submit this trip’s information" })).toBeDisabled();
    expect(returningApi.complete).not.toHaveBeenCalled();
  });

  it("updates the selected traveller contact only after new-number OTP and explicit confirmation", async () => {
    vi.mocked(returningApi.requestContact).mockResolvedValue({ expires_in_seconds: 300, resend_after_seconds: 30 });
    vi.mocked(returningApi.verifyContact).mockResolvedValue({ stage: "review" });
    vi.mocked(returningApi.history).mockResolvedValue({ ...history, group_requirements: { ...history.group_requirements, require_contact_phone: true }, contact_phone: "+919888888888", review_version: "review-v3" });
    render(<ReturningReview history={{ ...history, contact_phone: null, group_requirements: { ...history.group_requirements, require_contact_phone: true } }} groupName="Test trip" onFresh={vi.fn()} onReplace={vi.fn()} />);
    expect(screen.getByText(/This trip requires a current WhatsApp contact/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Passport front · Open preview/ }));
    fireEvent.load(await screen.findByRole("img", { name: "Passport front" }));
    fireEvent.change(screen.getByLabelText(/Staff code/), { target: { value: "0009" } });
    fireEvent.change(screen.getByRole("combobox", { name: /Trip meal/ }), { target: { value: "Jain" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the images/ }));
    expect(screen.getByRole("button", { name: "Submit this trip’s information" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Change WhatsApp contact" }));
    fireEvent.change(screen.getByLabelText("New WhatsApp number", { exact: false }), { target: { value: "9888888888" } });
    fireEvent.click(screen.getByRole("button", { name: "Send WhatsApp code" }));
    fireEvent.change(await screen.findByLabelText("WhatsApp verification code", { exact: false }), { target: { value: "123456" } });
    expect(returningApi.verifyContact).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Verify and update contact" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Use this verified number/ }));
    fireEvent.click(screen.getByRole("button", { name: "Verify and update contact" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("+919888888888")).toBeVisible();
    expect(screen.queryByText(/This trip requires a current WhatsApp contact/)).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /reviewed the images/ })).not.toBeChecked();
    expect(returningApi.requestContact).toHaveBeenCalledWith("+919888888888", expect.any(AbortSignal));
    expect(returningApi.verifyContact).toHaveBeenCalledWith("123456", expect.any(AbortSignal));
  });
});
