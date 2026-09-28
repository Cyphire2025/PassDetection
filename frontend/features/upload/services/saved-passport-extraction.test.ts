import { describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { pollSavedPassport } from "./saved-passport-extraction";

const initial = { id: "saved", status: "processing", extraction_status: "processing" } as PassportSubmission;
const ready = { ...initial, status: "ready_for_client_review", extraction_status: "extraction_complete", extracted_fields: { given_name: "Synthetic" } } as PassportSubmission;

function context() {
  let clock = 0;
  const controller = new AbortController();
  const onProgress = vi.fn();
  const wait = vi.fn(async (delay: number) => { clock += delay; });
  return { initial, signal: controller.signal, controller, onProgress, wait, now: () => clock };
}

describe("saved passport extraction controller", () => {
  it("opens saved busy uploads for manual entry immediately without polling", async () => {
    const options = context();
    const busy = { ...ready, extraction_status: "extraction_failed", processing_stage: "extraction_busy", manual_review_submission_allowed: true } as PassportSubmission;
    const fetchStatus = vi.fn();
    const result = await pollSavedPassport({ ...options, initial: busy, fetchStatus });
    expect(result.notice).toContain("Extraction is busy");
    expect(result.notice).toContain("AI verification");
    expect(result.retryAllowed).toBe(true);
    expect(options.wait).not.toHaveBeenCalled();
    expect(fetchStatus).not.toHaveBeenCalled();
  });
  it("explains that manually completed failed extractions still receive AI verification", async () => {
    const options = context();
    const failed = { ...ready, extraction_status: "extraction_failed", manual_review_submission_allowed: true } as PassportSubmission;
    const result = await pollSavedPassport({ ...options, initial: failed, fetchStatus: vi.fn() });
    expect(result.notice).toContain("AI verification will check them");
    expect(result.notice).not.toContain("staff approve");
  });
  it("recovers from a transient connection failure without reuploading or losing fields", async () => {
    const options = context();
    const fetchStatus = vi.fn().mockRejectedValueOnce({ code: "HTTP_503" }).mockResolvedValueOnce(ready);
    expect(await pollSavedPassport({ ...options, fetchStatus })).toMatchObject({ submission: ready, retryAllowed: false });
    expect(options.wait.mock.calls.map(([delay]) => delay)).toEqual([700, 1200]);
    expect(options.onProgress).toHaveBeenCalledWith(initial, null, "Reconnecting to your saved passport");
    expect(fetchStatus).toHaveBeenCalledWith("saved", options.signal);
  });
  it("ignores a late response after cancellation or family member change", async () => {
    const options = context();
    const fetchStatus = vi.fn(async () => { options.controller.abort(); return ready; });
    await expect(pollSavedPassport({ ...options, fetchStatus })).rejects.toMatchObject({ name: "AbortError" });
    expect(options.onProgress).toHaveBeenCalledTimes(1);
    expect(options.onProgress).not.toHaveBeenCalledWith(ready, expect.anything(), expect.anything());
  });
  it("does not reinterpret authorization/validation rejection as a network retry", async () => {
    const options = context();
    const error = { code: "HTTP_403" };
    const fetchStatus = vi.fn().mockRejectedValue(error);
    await expect(pollSavedPassport({ ...options, fetchStatus })).rejects.toBe(error);
    expect(fetchStatus).toHaveBeenCalledOnce();
  });
  it("reconciles one final time before presenting saved manual review", async () => {
    const options = context();
    const fetchStatus = vi.fn().mockResolvedValueOnce(initial).mockResolvedValueOnce(ready);
    const wait = async () => { await options.wait(65_000); };
    const result = await pollSavedPassport({ ...options, wait, fetchStatus });
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    expect(result.submission.extracted_fields).toEqual({ given_name: "Synthetic" });
    expect(result.notice).toBeNull();
  });
  it("retains the saved job and permits manual review when the poll window expires", async () => {
    const options = context();
    const fetchStatus = vi.fn().mockRejectedValue({ code: "NETWORK_ERROR" });
    const wait = async () => { await options.wait(65_000); };
    const result = await pollSavedPassport({ ...options, wait, fetchStatus });
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    expect(result.submission).toBe(initial);
    expect(result.retryAllowed).toBe(true);
    expect(result.notice).toContain("connection remained unstable");
  });
  it("also respects cancellation during final reconciliation", async () => {
    const options = context();
    const fetchStatus = vi.fn().mockResolvedValueOnce(initial).mockImplementationOnce(async () => { options.controller.abort(); throw new Error("cancelled"); });
    await expect(pollSavedPassport({ ...options, wait: async () => { await options.wait(65_000); }, fetchStatus })).rejects.toMatchObject({ name: "AbortError" });
  });
});
