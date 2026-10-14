import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { returningApi } from "../api/returning.api";
import { ReturningFlow } from "./returning-flow";
import type { ReturningHistory, ReturningMethod } from "../types";

vi.mock("../api/returning.api", () => ({ returningApi: { start: vi.fn(), requestOtp: vi.fn(), verifyOtp: vi.fn(), candidates: vi.fn(), selectCandidate: vi.fn(), passport: vi.fn(), challenge: vi.fn(), changeQuestion: vi.fn(), authorize: vi.fn(), history: vi.fn(), document: vi.fn() } }));
vi.mock("./returning-review", () => ({ ReturningReview: ({ history }: { history: ReturningHistory }) => <h1>{history.display_name}</h1> }));
vi.mock("@/features/upload/components/upload-flow-shell", () => ({ UploadHeader: ({ groupName }: { groupName: string }) => <h1>{groupName}</h1> }));
const group = { name: "Example trip", travel_date: "2026-12-01", return_date: "2026-12-08" } as UploadLinkResponse;
function setup(method: ReturningMethod) { return render(<ReturningFlow token="group-token" group={group} initialMethod={method} capabilities={{ enabled: true, code_label: "Producer code" }} onFresh={vi.fn()} onReplace={vi.fn()} />); }
function fillPassport() { fireEvent.change(screen.getByLabelText("Full passport number", { exact: false }), { target: { value: "A1234567" } }); }
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(returningApi.authorize).mockResolvedValue({ stage: "review" });
  vi.mocked(returningApi.history).mockResolvedValue({ display_name: "Verified Person" } as ReturningHistory);
});

describe("returning methods", () => {
  it("sends OTP inline, keeps candidates masked, and opens history only after complete passport proof", async () => {
    vi.mocked(returningApi.start).mockResolvedValue({ stage: "contact" });
    vi.mocked(returningApi.requestOtp).mockResolvedValue({ expires_in_seconds: 300, resend_after_seconds: 30 });
    vi.mocked(returningApi.verifyOtp).mockResolvedValue({ stage: "identify" });
    vi.mocked(returningApi.candidates).mockResolvedValue({ items: [{ handle: "opaque-one", label: "S*****", passport_hint: "••67" }, { handle: "opaque-two", label: "K*****", passport_hint: "••91" }], narrowing_required: false });
    vi.mocked(returningApi.selectCandidate).mockResolvedValue({ stage: "passport" });
    vi.mocked(returningApi.passport).mockResolvedValue({ stage: "confirm" });
    setup("phone");
    expect(screen.getByLabelText(/Enter verification code/)).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/WhatsApp number/), { target: { value: "9999999999" } });
    fireEvent.click(screen.getByRole("button", { name: "Send OTP" }));
    await waitFor(() => expect(screen.getByLabelText(/Enter verification code/)).toBeEnabled());
    expect(returningApi.requestOtp).toHaveBeenCalledOnce();
    fireEvent.change(screen.getByLabelText(/Enter verification code/), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify WhatsApp" }));
    fireEvent.click(await screen.findByText("S*****", { exact: true }));
    await screen.findByRole("button", { name: "Verify passport" });
    expect(returningApi.history).not.toHaveBeenCalled();
    fillPassport(); fireEvent.click(screen.getByRole("button", { name: "Verify passport" }));
    await screen.findByRole("heading", { name: "Verified Person" });
    expect(returningApi.selectCandidate).toHaveBeenCalledWith("opaque-one", expect.any(AbortSignal));
    expect(returningApi.authorize).toHaveBeenCalledWith(expect.any(AbortSignal));
    expect(screen.queryByText(/permission to view/)).not.toBeInTheDocument();
  });
  it("keeps passport existence private until the date is verified and removes issuing country", async () => {
    vi.mocked(returningApi.start).mockResolvedValue({ stage: "identify" });
    vi.mocked(returningApi.passport).mockResolvedValue({ stage: "challenge", questions: ["date_of_birth"], can_change_question: true });
    vi.mocked(returningApi.challenge).mockResolvedValue({ stage: "confirm" });
    setup("passport"); fillPassport();
    expect(screen.queryByLabelText(/Issuing country/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const dob = await screen.findByLabelText("Date of birth", { exact: false, selector: 'input[type="text"]' });
    expect(returningApi.history).not.toHaveBeenCalled(); expect(returningApi.authorize).not.toHaveBeenCalled();
    fireEvent.change(dob, { target: { value: "01/01/1990" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and view passport" }));
    await screen.findByRole("heading", { name: "Verified Person" });
    expect(returningApi.challenge).toHaveBeenCalledWith({ date_of_birth: "1990-01-01" }, expect.any(AbortSignal));
    expect(returningApi.requestOtp).not.toHaveBeenCalled();
    expect(returningApi.start).toHaveBeenCalledWith({ group_token: "group-token", method: "passport", passport_number: "A1234567" }, expect.any(AbortSignal));
  });
  it("preserves leading zeros in individual codes and requires complete passport proof", async () => {
    vi.mocked(returningApi.start).mockResolvedValue({ stage: "identify" });
    vi.mocked(returningApi.passport).mockResolvedValue({ stage: "confirm" });
    setup("code");
    fireEvent.change(screen.getByLabelText(/Producer code/), { target: { value: "00019" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("button", { name: "Verify passport" });
    expect(returningApi.history).not.toHaveBeenCalled();
    fillPassport(); fireEvent.click(screen.getByRole("button", { name: "Verify passport" }));
    await screen.findByRole("heading", { name: "Verified Person" });
    expect(returningApi.start).toHaveBeenCalledWith({ group_token: "group-token", method: "code", individual_code: "00019" }, expect.any(AbortSignal));
    expect(returningApi.requestOtp).not.toHaveBeenCalled();
  });
  it("keeps failed proof locked and focuses the new-traveller action", async () => {
    vi.mocked(returningApi.start).mockResolvedValue({ stage: "identify" });
    vi.mocked(returningApi.passport).mockRejectedValue({ message: "The supplied information could not be verified." });
    setup("code"); fireEvent.change(screen.getByLabelText(/Producer code/), { target: { value: "00019" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByRole("button", { name: "Verify passport" });
    fillPassport(); fireEvent.click(screen.getByRole("button", { name: "Verify passport" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn’t verify a saved record");
    expect(returningApi.history).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Continue as a new traveller" })).toHaveFocus());
  });
});
