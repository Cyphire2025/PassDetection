import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { returningApi } from "../api/returning.api";
import { ReturningFlow } from "./returning-flow";
import type { ReturningHistory, ReturningMethod } from "../types";

vi.mock("../api/returning.api", () => ({ returningApi: { start: vi.fn(), requestOtp: vi.fn(), verifyOtp: vi.fn(), candidates: vi.fn(), selectCandidate: vi.fn(), passport: vi.fn(), challenge: vi.fn(), changeQuestion: vi.fn(), confirm: vi.fn(), history: vi.fn(), complete: vi.fn(), document: vi.fn() } }));
vi.mock("@/features/upload/components/upload-flow-shell", () => ({ UploadHeader: ({ groupName }: { groupName: string }) => <h1>{groupName}</h1> }));
const group = { name: "Example trip", travel_date: "2026-12-01", return_date: "2026-12-08" } as UploadLinkResponse;
const history: ReturningHistory = { display_name: "Verified Person", contact_phone: "+919999999999", passport: { id: "passport-a", number: "A1234567", issuing_country: "IND", document_type: "P", date_of_birth: "1990-01-01", issue_date: "2020-01-01", expiry_date: "2030-01-01", revision: 1 }, documents: [], suitability: { outcome: "suitable", reason_codes: [] }, group_requirements: { custom_questions: [], custom_details: [], require_selfie: false, require_contact_phone: false }, question_version: "v1", review_version: "review-v1", participation_revision: null };
function setup(method: ReturningMethod) { return render(<ReturningFlow token="group-token" group={group} initialMethod={method} capabilities={{ enabled: true, code_label: "Producer code" }} onFresh={vi.fn()} onReplace={vi.fn()} />); }
function fillPassport() {
  fireEvent.change(screen.getByLabelText("Full passport number", { exact: false }), { target: { value: "A1234567" } });
  fireEvent.change(screen.getByRole("combobox", { name: /Issuing country/ }), { target: { value: "IND" } });
}
async function confirm() {
  fireEvent.click(await screen.findByRole("checkbox", { name: /permission to view/ }));
  fireEvent.click(screen.getByRole("button", { name: "Review saved details" }));
  await screen.findByRole("heading", { name: "Review your saved passport" });
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(returningApi.confirm).mockResolvedValue({ stage: "review" });
  vi.mocked(returningApi.history).mockResolvedValue(history);
});

describe("returning methods", () => {
  it("keeps phone candidates masked and does not retrieve history before full passport and confirmation", async () => {
    vi.mocked(returningApi.start).mockResolvedValue({ stage: "contact" });
    vi.mocked(returningApi.requestOtp).mockResolvedValue({ expires_in_seconds: 300, resend_after_seconds: 30 });
    vi.mocked(returningApi.verifyOtp).mockResolvedValue({ stage: "identify" });
    vi.mocked(returningApi.candidates).mockResolvedValue({ items: [{ handle: "opaque-one", label: "S*****", passport_hint: "••67" }, { handle: "opaque-two", label: "K*****", passport_hint: "••91" }], narrowing_required: false });
    vi.mocked(returningApi.selectCandidate).mockResolvedValue({ stage: "passport" });
    vi.mocked(returningApi.passport).mockResolvedValue({ stage: "confirm" });
    setup("phone");
    fireEvent.change(screen.getByLabelText("WhatsApp number", { exact: false }), { target: { value: "9999999999" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(await screen.findByRole("button", { name: "Send WhatsApp code" }));
    fireEvent.change(await screen.findByLabelText("WhatsApp verification code", { exact: false }), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify code" }));
    fireEvent.click(await screen.findByRole("button", { name: /S\*\*\*\*\*/ }));
    await screen.findByRole("heading", { name: "Confirm the full passport" });
    expect(returningApi.history).not.toHaveBeenCalled();
    expect(returningApi.selectCandidate).toHaveBeenCalledWith("opaque-one", expect.any(AbortSignal));
    fillPassport();
    fireEvent.click(screen.getByRole("button", { name: "Check passport" }));
    await confirm();
    expect(returningApi.challenge).not.toHaveBeenCalled();
    expect(returningApi.document).not.toHaveBeenCalled();
  });

  it("retains passport entry, uses the server DOB challenge, and never sends routine OTP", async () => {
    vi.mocked(returningApi.start).mockResolvedValue({ stage: "identify" });
    vi.mocked(returningApi.passport).mockResolvedValue({ stage: "challenge", questions: ["date_of_birth"], can_change_question: true });
    vi.mocked(returningApi.challenge).mockResolvedValue({ stage: "confirm" });
    setup("passport");
    expect(screen.queryByLabelText("WhatsApp number")).not.toBeInTheDocument();
    fillPassport();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const dob = await screen.findByLabelText("Date of birth", { exact: false, selector: 'input[type="text"]' });
    expect(returningApi.passport).toHaveBeenCalledWith({}, expect.any(AbortSignal));
    expect(screen.queryByLabelText("Full passport number")).not.toBeInTheDocument();
    fireEvent.change(dob, { target: { value: "01/01/1990" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify passport details" }));
    await confirm();
    expect(returningApi.challenge).toHaveBeenCalledWith({ date_of_birth: "1990-01-01" }, expect.any(AbortSignal));
    expect(returningApi.requestOtp).not.toHaveBeenCalled();
    expect(returningApi.start).toHaveBeenCalledWith({ group_token: "group-token", method: "passport", passport_number: "A1234567", issuing_country: "IND", document_type: "P" }, expect.any(AbortSignal));
  });

  it("preserves leading zeros in codes and still requires a complete passport", async () => {
    vi.mocked(returningApi.start).mockResolvedValue({ stage: "identify" });
    vi.mocked(returningApi.passport).mockResolvedValue({ stage: "confirm" });
    setup("code");
    fireEvent.change(screen.getByLabelText("Producer code", { exact: false }), { target: { value: "00019" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Confirm the full passport" });
    expect(returningApi.history).not.toHaveBeenCalled();
    fillPassport();
    fireEvent.click(screen.getByRole("button", { name: "Check passport" }));
    await confirm();
    expect(returningApi.start).toHaveBeenCalledWith({ group_token: "group-token", method: "code", individual_code: "00019", document_type: "P" }, expect.any(AbortSignal));
    expect(returningApi.requestOtp).not.toHaveBeenCalled();
    expect(returningApi.challenge).not.toHaveBeenCalled();
  });

  it("keeps failed proof locked and offers current document collection", async () => {
    vi.mocked(returningApi.start).mockResolvedValue({ stage: "identify" });
    vi.mocked(returningApi.passport).mockRejectedValue({ message: "The supplied information could not be verified." });
    setup("code");
    fireEvent.change(screen.getByLabelText("Producer code", { exact: false }), { target: { value: "00019" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("heading", { name: "Confirm the full passport" });
    fillPassport();
    fireEvent.click(screen.getByRole("button", { name: "Check passport" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("could not be verified"));
    expect(returningApi.history).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "New traveller / Upload current documents" })).toBeEnabled();
  });
});
