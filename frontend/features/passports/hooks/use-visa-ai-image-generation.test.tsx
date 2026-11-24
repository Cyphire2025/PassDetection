import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { passportsApi } from "../api/passports.api";
import { waitForVisaAiGenerationJob } from "../services/visa-ai-generation-polling";
import { useVisaAiImageGeneration } from "./use-visa-ai-image-generation";
import { queuedJob } from "./passport-image-editor.test-fixtures";

vi.mock("../api/passports.api", () => ({ passportsApi: {
  getActiveVisaAiGenerationJob: vi.fn(), createVisaAiGenerationJob: vi.fn(), getVisaAiGenerationJob: vi.fn(),
} }));

function options() {
  return { submissionId: "passport-1", isVisaPhoto: true, canGenerate: true,
    imageLibrary: [], setImageLibrary: vi.fn(), setError: vi.fn() };
}

describe("durable Visa photo generation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.mocked(passportsApi.getActiveVisaAiGenerationJob).mockResolvedValue(null);
  });
  afterEach(() => vi.useRealTimers());

  it("admits one generation and publishes its saved library result", async () => {
    const saved = { id: "image-2", image_url: "/api/private/image-2", prompt: "Studio lighting",
      model: "synthetic", created_at: queuedJob.created_at, is_current: false };
    vi.mocked(passportsApi.createVisaAiGenerationJob).mockResolvedValue(queuedJob);
    vi.mocked(passportsApi.getVisaAiGenerationJob).mockResolvedValue({ ...queuedJob, status: "succeeded", result: saved });
    const props = options();
    const { result } = renderHook(() => useVisaAiImageGeneration(props));
    await act(async () => {});
    let generation!: Promise<void>;
    act(() => { generation = result.current.generateAiPreview(); void result.current.generateAiPreview(); });
    expect(passportsApi.createVisaAiGenerationJob).toHaveBeenCalledOnce();
    expect(result.current.isGenerating).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); await generation; });
    expect(result.current.isGenerating).toBe(false);
    expect(result.current.featuredGenerationId).toBe(saved.id);
    expect(props.setImageLibrary).toHaveBeenCalledOnce();
    const updateLibrary = props.setImageLibrary.mock.calls[0][0];
    expect(updateLibrary([])).toEqual([{ ...saved, image_type: "visa_photo", source: "ai_generated" }]);
  });

  it("resumes an existing job and stops polling on close without cancelling that saved job", async () => {
    vi.mocked(passportsApi.getActiveVisaAiGenerationJob).mockResolvedValue(queuedJob);
    const props = options();
    const { result, unmount } = renderHook(() => useVisaAiImageGeneration(props));
    await act(async () => {});
    expect(result.current.isGenerating).toBe(true);
    const signal = vi.mocked(passportsApi.getActiveVisaAiGenerationJob).mock.calls[0][1]!;
    unmount();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(signal.aborted).toBe(true);
    expect(passportsApi.getVisaAiGenerationJob).not.toHaveBeenCalled();
    expect(passportsApi.createVisaAiGenerationJob).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ends polling after four consecutive transport failures", async () => {
    vi.mocked(passportsApi.getVisaAiGenerationJob).mockRejectedValue(new Error("Transport unavailable"));
    const controller = new AbortController();
    const failure = expect(waitForVisaAiGenerationJob("passport-1", queuedJob, controller.signal))
      .rejects.toThrow("Transport unavailable");
    await vi.advanceTimersByTimeAsync(8_000);
    await failure;
    expect(passportsApi.getVisaAiGenerationJob).toHaveBeenCalledTimes(4);
  });
});
