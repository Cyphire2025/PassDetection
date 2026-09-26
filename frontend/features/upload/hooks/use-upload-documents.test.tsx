import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { createFamilyMembers, emptyDocumentBundle } from "../services/upload-flow-helpers";
import { readUploadRecoveryRecord } from "../services/upload-flow-session";
import { useUploadDocuments } from "./use-upload-documents";
import { useUploadOperation } from "./use-upload-operation";

const mocks = vi.hoisted(() => ({ upload: vi.fn(), poll: vi.fn(), normalize: vi.fn(), scanAgain: vi.fn(), discard: vi.fn(), status: vi.fn() }));
vi.mock("./use-upload", () => ({ useUploadPassport: () => ({ mutateAsync: mocks.upload }) }));
vi.mock("../services/saved-passport-extraction", () => ({ pollSavedPassport: mocks.poll }));
vi.mock("../services/passport-perspective-correction", () => ({ normalizePassportFile: mocks.normalize }));
vi.mock("../api/upload.api", () => ({ uploadApi: { scanAgain: mocks.scanAgain, discardUpload: mocks.discard, getUploadStatus: mocks.status } }));

const saved = { id: "saved-one", client_name: "Synthetic Traveller", status: "processing", extraction_status: "processing",
  extracted_fields: { given_names: "Synthetic", surname: "Traveller" }, image_s3_key: "saved/image.jpg" } as PassportSubmission;
const completed = { ...saved, status: "ready_for_client_review", extraction_status: "ready_for_review" } as PassportSubmission;
type Context = Omit<Parameters<typeof useUploadDocuments>[0], "operation">;
function context(overrides: Partial<Context> = {}): Context {
  return { token: "document-test", step: "METHOD_SELECT", flowMode: "single", activeFamilyIndex: 0,
    familyMembers: createFamilyMembers(2), updateFamilyMember: vi.fn(), clientName: "Synthetic Traveller", setClientName: vi.fn(),
    submission: null, setSubmission: vi.fn(), setReviewFields: vi.fn(), singleUploadIdempotencyKey: "00000000-0000-4000-8000-000000000001",
    setSingleUploadIdempotencyKey: vi.fn(), qualifierSelectionToken: null, activeVisaPhotoSource: null,
    setVisaSelfie: vi.fn(), setDocumentBundle: vi.fn(), selectFamilyMember: vi.fn(), setStep: vi.fn(),
    setUploadError: vi.fn(), setExtractionNotice: vi.fn(), setCanRetryExtraction: vi.fn(), ...overrides };
}
function harness(input: Context) {
  return renderHook((props: Context) => {
    const operation = useUploadOperation(props.token);
    return { documents: useUploadDocuments({ ...props, operation }), operation };
  }, { initialProps: input });
}
const file = () => new File(["synthetic passport"], "passport.jpg", { type: "image/jpeg" });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }

beforeEach(() => {
  vi.resetAllMocks(); window.sessionStorage.clear();
  mocks.upload.mockResolvedValue(saved);
  mocks.poll.mockResolvedValue({ submission: completed, notice: null, retryAllowed: false });
  mocks.normalize.mockImplementation(async (value: File) => ({ file: value }));
  mocks.scanAgain.mockResolvedValue(completed);
  mocks.discard.mockResolvedValue(undefined);
});

describe("saved document controller", () => {
  it("persists the upload credential and acknowledged object before extraction", async () => {
    const input = context(); const { result } = harness(input);
    mocks.upload.mockImplementation(async () => {
      expect(readUploadRecoveryRecord(input.token)?.idempotencyKey).toBe(input.singleUploadIdempotencyKey);
      return saved;
    });
    mocks.poll.mockImplementation(async ({ onProgress, fetchStatus }) => {
      expect(readUploadRecoveryRecord(input.token)?.submissionId).toBe(saved.id);
      await fetchStatus(saved.id, new AbortController().signal);
      onProgress(saved, 0.5, "Reading saved passport");
      return { submission: completed, notice: null, retryAllowed: false };
    });
    await act(async () => { await result.current.documents.processUpload(file(), null, "file", "file", false); });
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(mocks.status).toHaveBeenCalledWith(input.token, saved.id, input.singleUploadIdempotencyKey, expect.any(AbortSignal));
    expect(input.setSubmission).toHaveBeenLastCalledWith(completed);
    expect(input.setDocumentBundle).toHaveBeenCalledWith(emptyDocumentBundle());
    expect(input.setStep).toHaveBeenLastCalledWith("REVIEW");
    expect(result.current.operation.isBusy()).toBe(false);
  });
  it("keeps saved bytes reviewable after extraction fails instead of uploading again", async () => {
    mocks.poll.mockRejectedValue(new Error("extractor disconnected"));
    const input = context(); const { result } = harness(input);
    await act(async () => { await result.current.documents.processUpload(file(), null, "camera", "camera", false); });
    expect(input.setSubmission).toHaveBeenLastCalledWith(saved);
    expect(input.setCanRetryExtraction).toHaveBeenLastCalledWith(true);
    expect(input.setStep).toHaveBeenLastCalledWith("REVIEW");
    expect(readUploadRecoveryRecord(input.token)?.submissionId).toBe(saved.id);
    expect(mocks.upload).toHaveBeenCalledTimes(1);
  });
  it.each([false, true])("advances only the uploaded family member; final member=%s", async (last) => {
    const members = createFamilyMembers(2); members[0].name = "Synthetic One";
    if (last) members[1].submission = completed;
    const input = context({ flowMode: "family", familyMembers: members }); const { result } = harness(input);
    await act(async () => { await result.current.documents.processUpload(null, null, "file", "file", false); });
    expect(input.updateFamilyMember).toHaveBeenCalledWith(0, expect.objectContaining({ submission: saved, visaSelfie: null }));
    expect(mocks.upload.mock.calls[0][0].uploadIdempotencyKey).toBe(members[0].uploadIdempotencyKey);
    expect(input.setStep).toHaveBeenLastCalledWith(last ? "FAMILY_REVIEW" : "METHOD_SELECT");
    if (!last) expect(input.selectFamilyMember).toHaveBeenCalledWith(1);
  });
  it("retains a family member's saved document when extraction fails", async () => {
    mocks.poll.mockRejectedValue(new Error("extractor disconnected"));
    const members = createFamilyMembers(2); members[0].name = "Synthetic One";
    const input = context({ flowMode: "family", familyMembers: members }); const { result } = harness(input);
    await act(async () => { await result.current.documents.processUpload(file(), null, "camera", "camera", false); });
    expect(input.updateFamilyMember).toHaveBeenCalledWith(0, expect.objectContaining({ submission: saved, canRetryExtraction: true }));
    expect(input.setStep).toHaveBeenLastCalledWith("FAMILY_REVIEW");
  });
  it("retains the acknowledged family upload when extraction is cancelled", async () => {
    const extraction = deferred<{ submission: PassportSubmission; notice: null; retryAllowed: false }>();
    mocks.poll.mockReturnValue(extraction.promise);
    const members = createFamilyMembers(2); members[0].name = "Synthetic One";
    const input = context({ flowMode: "family", familyMembers: members }); const { result } = harness(input);
    let pending!: Promise<void>;
    await act(async () => { pending = result.current.documents.processUpload(file(), null, "camera", "camera", false); await Promise.resolve(); });
    expect(input.updateFamilyMember).toHaveBeenCalledExactlyOnceWith(0, { submission: saved });
    act(() => result.current.documents.handleBackToUploadMethods());
    await act(async () => { extraction.resolve({ submission: completed, notice: null, retryAllowed: false }); await pending; });
    expect(input.updateFamilyMember).toHaveBeenCalledTimes(1);
    expect(input.setStep).toHaveBeenLastCalledWith("METHOD_SELECT");
    expect(mocks.upload).toHaveBeenCalledTimes(1);
  });
  it("keeps the credential when persistence itself fails", async () => {
    mocks.upload.mockRejectedValue(new Error("storage unavailable"));
    const input = context(); const { result } = harness(input);
    await act(async () => { await result.current.documents.processUpload(null, null, "file", "file", false); });
    expect(input.setSubmission).not.toHaveBeenCalled();
    expect(input.setStep).toHaveBeenLastCalledWith("METHOD_SELECT");
    expect(readUploadRecoveryRecord(input.token)?.idempotencyKey).toBe(input.singleUploadIdempotencyKey);
    expect(input.setUploadError).toHaveBeenLastCalledWith(expect.any(String));
  });
  it("shows the retryable capacity message and preserves the credential for explicit retry", async () => {
    mocks.upload.mockRejectedValueOnce({ isAxiosError: true, response: { status: 503,
      data: { error: { code: "IMAGE_PROCESSING_BUSY", message: "Image processing is busy. Please try again shortly." } } } });
    const input = context(); const { result } = harness(input);
    await act(async () => { await result.current.documents.processUpload(file(), null, "file", "file", false); });
    expect(input.setUploadError).toHaveBeenLastCalledWith("Image processing is busy. Please try again shortly.");
    expect(input.setStep).toHaveBeenLastCalledWith("METHOD_SELECT");
    expect(readUploadRecoveryRecord(input.token)?.idempotencyKey).toBe(input.singleUploadIdempotencyKey);
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(mocks.poll).not.toHaveBeenCalled();
    await act(async () => { await result.current.documents.processUpload(file(), null, "file", "file", false); });
    expect(mocks.upload).toHaveBeenCalledTimes(2);
    expect(mocks.upload.mock.calls[1][0].uploadIdempotencyKey).toBe(input.singleUploadIdempotencyKey);
    expect(input.setStep).toHaveBeenLastCalledWith("REVIEW");
  });
  it("ignores late acknowledgement after cancellation without unlocking the next attempt", async () => {
    const response = deferred<PassportSubmission>(); mocks.upload.mockReturnValue(response.promise);
    const input = context(); const { result } = harness(input);
    let uploading!: Promise<void>;
    act(() => { uploading = result.current.documents.processUpload(null, null, "file", "file", false); });
    await act(async () => { await Promise.resolve(); });
    act(() => result.current.documents.handleBackToUploadMethods());
    const next = deferred<PassportSubmission>(); mocks.upload.mockReturnValue(next.promise);
    let replacement!: Promise<void>;
    act(() => { replacement = result.current.documents.processUpload(null, null, "file", "file", false); });
    await act(async () => { response.resolve(saved); await uploading; });
    expect(result.current.operation.isBusy()).toBe(true);
    expect(input.setSubmission).not.toHaveBeenCalled();
    await act(async () => { next.resolve(completed); await replacement; });
    expect(input.setSubmission).toHaveBeenLastCalledWith(completed);
  });
  it("deduplicates concurrent upload clicks", async () => {
    const response = deferred<PassportSubmission>(); mocks.upload.mockReturnValue(response.promise);
    const input = context(); const { result } = harness(input);
    let first!: Promise<void>; let second!: Promise<void>;
    act(() => { first = result.current.documents.processUpload(null, null, "file", "file", false); second = result.current.documents.processUpload(null, null, "file", "file", false); });
    await act(async () => { response.resolve(completed); await Promise.all([first, second]); });
    expect(mocks.upload).toHaveBeenCalledTimes(1);
  });
  it("retries the existing object and preserves manually edited fields", async () => {
    const input = context({ submission: saved }); const { result } = harness(input);
    await act(async () => { await result.current.documents.handleScanAgain(); });
    expect(mocks.upload).not.toHaveBeenCalled();
    expect(mocks.scanAgain).toHaveBeenCalledWith(input.token, saved.id, input.singleUploadIdempotencyKey, expect.any(AbortSignal));
    const merge = vi.mocked(input.setReviewFields).mock.calls[0][0];
    expect(typeof merge).toBe("function");
    if (typeof merge === "function") expect(merge({ surname: "Manual correction" }).surname).toBe("Manual correction");
  });
  it("uses the selected family member's credential for retry", async () => {
    const members = createFamilyMembers(2); members[1].submission = saved;
    const input = context({ familyMembers: members }); const { result } = harness(input);
    await act(async () => { await result.current.documents.handleFamilyScanAgain(1); });
    expect(mocks.scanAgain.mock.calls[0][2]).toBe(members[1].uploadIdempotencyKey);
    const patch = vi.mocked(input.updateFamilyMember).mock.calls.at(-1)![1];
    if (typeof patch === "function") expect(patch({ ...members[1], reviewFields: { surname: "Manual" } }).reviewFields?.surname).toBe("Manual");
  });
  it("preserves the saved object and credential when discard fails", async () => {
    mocks.discard.mockRejectedValue(new Error("storage unavailable"));
    const input = context({ submission: saved }); const { result } = harness(input);
    await act(async () => { await result.current.documents.replaceSavedPassport(null); });
    expect(input.setSubmission).not.toHaveBeenCalled();
    expect(input.setSingleUploadIdempotencyKey).not.toHaveBeenCalled();
    expect(result.current.documents.isReplacingSavedPassport).toBe(false);
  });
  it.each([false, true])("rotates the credential only after successful discard, family=%s", async (family) => {
    const members = createFamilyMembers(2); members[0].submission = saved;
    const input = context({ submission: saved, familyMembers: members }); const { result } = harness(input);
    await act(async () => { await result.current.documents.replaceSavedPassport(family ? 0 : null); });
    expect(mocks.discard).toHaveBeenCalledTimes(1);
    if (family) expect(input.updateFamilyMember).toHaveBeenCalledWith(0, expect.objectContaining({ submission: null, uploadIdempotencyKey: expect.any(String) }));
    else {
      expect(input.setSubmission).toHaveBeenCalledWith(null);
      expect(readUploadRecoveryRecord(input.token)?.idempotencyKey).not.toBe(input.singleUploadIdempotencyKey);
    }
  });
  it.each([false, true])("resumes without repeating upload, extraction failure=%s", async (failed) => {
    if (failed) mocks.poll.mockRejectedValue(new Error("offline"));
    const input = context(); const { result, rerender } = harness(input);
    act(() => result.current.documents.queueSubmissionResume(saved));
    rerender({ ...input, step: "UPLOADING" });
    await waitFor(() => expect(input.setStep).toHaveBeenCalledWith("REVIEW"));
    expect(mocks.upload).not.toHaveBeenCalled();
    expect(result.current.documents.resumeSubmissionId).toBeNull();
    if (failed) expect(input.setCanRetryExtraction).toHaveBeenCalledWith(true);
    else expect(input.setSubmission).toHaveBeenCalledWith(completed);
  });
});
