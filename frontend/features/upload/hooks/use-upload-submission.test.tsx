import { act, renderHook } from "@testing-library/react";
import type { FormEvent } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { getUploadFlowSettings } from "../services/configured-upload";
import { createFamilyMembers } from "../services/upload-flow-helpers";
import { useUploadOperation } from "./use-upload-operation";
import { useUploadSubmission } from "./use-upload-submission";

const mocks = vi.hoisted(() => ({ submit: vi.fn(), refreshLink: vi.fn() }));
vi.mock("./use-upload", () => ({ useSubmitClientPassportReview: () => ({ mutateAsync: mocks.submit }) }));
vi.mock("@/features/passports/api/upload-links.api", () => ({ uploadLinksApi: { getByToken: mocks.refreshLink } }));
const saved = { id: "saved-one", image_s3_key: "", status: "ready_for_client_review" } as PassportSubmission;
const complete = { ...saved, status: "submitted", client_review_status: "submitted" } as PassportSubmission;
type Context = Omit<Parameters<typeof useUploadSubmission>[0], "operation">;
function context(): Context {
  return {
    token: "synthetic-token", submission: saved, singleUploadIdempotencyKey: "single-credential", familyGroupId: "family-group",
    familyMembers: createFamilyMembers(2).map((member, index) => ({ ...member, name: `Synthetic ${index}`, email: `member${index}@example.com`, phone: "+919999999999", submission: { ...saved, id: `saved-${index}` } })),
    updateFamilyMember: vi.fn(), contactVerification: {
      getProof: vi.fn(() => ({ id: "proof", sessionId: "credential", email: "synthetic@example.com", phone: "+919999999999", expiresAt: Date.now() + 60_000 })),
      edit: vi.fn(), invalidate: vi.fn(),
    },
    setSubmission: vi.fn(), setClientName: vi.fn(), setStep: vi.fn(), setUploadError: vi.fn(), setLinkError: vi.fn(),
    canReviewSubmission: () => true, requiresPassportReview: () => false, settings: getUploadFlowSettings(),
    draft: { clientName: "Synthetic Traveller", clientEmail: "synthetic@example.com", clientPhone: "+919999999999", reviewFields: {},
      departureCity: "", baseCity: "", nearestDomesticAirport: "", staffCode: "", agentEmployeeCode: "", designation: "", agencyDealershipName: "", mealPreference: "", customAnswers: {}, customDetailAnswers: {} },
  };
}
function harness(input: Context) {
  return renderHook((props: Context) => {
    const operation = useUploadOperation(props.token);
    return { submission: useUploadSubmission({ ...props, operation }), operation };
  }, { initialProps: input });
}
const event = () => ({ preventDefault: vi.fn() }) as unknown as FormEvent;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => { vi.resetAllMocks(); mocks.submit.mockResolvedValue(complete); mocks.refreshLink.mockResolvedValue({}); });

describe("review submission controller", () => {
  it("sends only configured answers and cleans fields while retaining each contact credential", async () => {
    const input = context();
    input.settings.enabledCustomQuestions = [{ id: "enabled", label: "Question", enabled: true, options: ["Yes"] }];
    input.settings.enabledCustomDetails = [{ id: "detail", label: "Detail", enabled: true }];
    input.draft = { ...input.draft, baseCity: " Delhi ", staffCode: " staff ", customAnswers: { enabled: "Yes", stale: "Hidden" }, customDetailAnswers: { detail: "Present", stale: "Hidden" }, reviewFields: { surname: "" } };
    const { result } = harness(input);
    await act(async () => { await result.current.submission.handleFinalSubmit(event()); });
    expect(mocks.submit).toHaveBeenCalledWith(expect.objectContaining({ submissionId: saved.id, uploadSessionId: input.singleUploadIdempotencyKey,
      phone_verification_id: "proof", client_email: input.draft.clientEmail, base_city: "Delhi", staff_code: "staff", confirmed_fields: { surname: "" },
      custom_answers: [{ question_id: "enabled", value: "Yes" }], custom_detail_answers: [{ detail_id: "detail", value: "Present" }] }));
    expect(input.setSubmission).toHaveBeenCalledWith(complete);
    expect(input.setStep).toHaveBeenLastCalledWith("SUCCESS");
  });
  it.each(["single", "family"] as const)("reopens contact verification before any %s mutation", async (mode) => {
    const input = context(); vi.mocked(input.contactVerification.getProof).mockReturnValue(null);
    const { result } = harness(input);
    await act(async () => { await (mode === "single" ? result.current.submission.handleFinalSubmit(event()) : result.current.submission.handleFamilySubmit(event())); });
    expect(input.contactVerification.edit).toHaveBeenCalledWith(mode === "single" ? saved.id : "saved-0");
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it.each(["single", "family"] as const)("rejects invalid %s fields before mutation", async (mode) => {
    const input = context(); input.draft.clientPhone = "bad"; input.familyMembers[1].phone = "bad";
    const { result } = harness(input);
    await act(async () => { await (mode === "single" ? result.current.submission.handleFinalSubmit(event()) : result.current.submission.handleFamilySubmit(event())); });
    expect(input.setUploadError).toHaveBeenCalled(); expect(mocks.submit).not.toHaveBeenCalled();
  });
  it("admits only one synchronous submit and ignores completion after cancellation", async () => {
    const response = deferred<PassportSubmission>(); mocks.submit.mockReturnValue(response.promise);
    const input = context(); const { result } = harness(input); let pending!: Promise<void>;
    act(() => { pending = result.current.submission.handleFinalSubmit(event()); void result.current.submission.handleFinalSubmit(event()); });
    expect(mocks.submit).toHaveBeenCalledTimes(1);
    act(() => result.current.operation.cancel());
    await act(async () => { response.resolve(complete); await pending; });
    expect(input.setSubmission).not.toHaveBeenCalled(); expect(input.setStep).not.toHaveBeenCalledWith("SUCCESS");
  });
  it("retains each acknowledged family row when the next fails and retries only pending rows", async () => {
    const input = context();
    mocks.submit.mockResolvedValueOnce({ ...complete, id: "saved-0" }).mockRejectedValueOnce(new Error("temporary failure"));
    const { result, rerender } = harness(input);
    await act(async () => { await result.current.submission.handleFamilySubmit(event()); });
    expect(input.updateFamilyMember).toHaveBeenCalledExactlyOnceWith(0, { submission: { ...complete, id: "saved-0" } });
    expect(input.setStep).toHaveBeenLastCalledWith("FAMILY_REVIEW");
    const updated = { ...input, familyMembers: input.familyMembers.map((member, index) => index === 0 ? { ...member, submission: { ...complete, id: "saved-0" } } : member) };
    rerender(updated); mocks.submit.mockClear();
    await act(async () => { await result.current.submission.handleFamilySubmit(event()); });
    expect(mocks.submit).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ submissionId: "saved-1", family_member_index: 1,
      client_email: "member1@example.com", family_head_email: "member0@example.com", uploadSessionId: input.familyMembers[1].uploadIdempotencyKey }));
    expect(input.setStep).toHaveBeenLastCalledWith("SUCCESS");
  });
  it.each(["single", "family"] as const)("invalidates expired %s proof while preserving a reviewable form", async (mode) => {
    mocks.submit.mockRejectedValue({ code: "CONTACT_VERIFICATION_REQUIRED", message: "Verify again." });
    const input = context(); const { result } = harness(input);
    await act(async () => { await (mode === "single" ? result.current.submission.handleFinalSubmit(event()) : result.current.submission.handleFamilySubmit(event())); });
    expect(input.contactVerification.invalidate).toHaveBeenCalledWith(mode === "single" ? saved.id : "saved-0");
    expect(input.setStep).toHaveBeenLastCalledWith(mode === "single" ? "REVIEW" : "FAMILY_REVIEW");
    expect(result.current.operation.isBusy()).toBe(false);
  });
  it("stops later family submissions after cancellation", async () => {
    const response = deferred<PassportSubmission>(); mocks.submit.mockReturnValue(response.promise);
    const input = context(); const { result } = harness(input); let pending!: Promise<void>;
    act(() => { pending = result.current.submission.handleFamilySubmit(event()); });
    act(() => result.current.operation.cancel());
    await act(async () => { response.resolve(complete); await pending; });
    expect(mocks.submit).toHaveBeenCalledTimes(1); expect(input.updateFamilyMember).not.toHaveBeenCalled();
  });
  it("does not publish an old link failure after the upload token changes", async () => {
    const response = deferred<unknown>(); mocks.refreshLink.mockReturnValue(response.promise);
    mocks.submit.mockRejectedValue({ status: 410 });
    const input = context(); const { result, rerender } = harness(input); let pending!: Promise<void>;
    await act(async () => { pending = result.current.submission.handleFinalSubmit(event()); await Promise.resolve(); });
    expect(mocks.refreshLink).toHaveBeenCalledWith(input.token);
    rerender({ ...input, token: "new-token" });
    await act(async () => { response.reject(new Error("old link expired")); await pending; });
    expect(input.setLinkError).not.toHaveBeenCalled();
  });
});
