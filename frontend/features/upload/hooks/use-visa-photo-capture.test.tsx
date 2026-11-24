import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useVisaCameraState } from "./use-visa-camera-state";
import { useVisaPhotoCapture } from "./use-visa-photo-capture";

const mocks = vi.hoisted(() => ({ capture: vi.fn(), encode: vi.fn(), decode: vi.fn(), detect: vi.fn(), evaluate: vi.fn() }));
vi.mock("../services/camera-capture", async (original) => ({
  ...await original<typeof import("../services/camera-capture")>(), captureBestCameraSource: mocks.capture,
}));
vi.mock("../services/visa-camera-image-encoding", () => ({ decodeVisaPhoto: mocks.decode, canvasToJpeg: vi.fn() }));
vi.mock("./use-visa-final-face-detection", () => ({ useVisaFinalFaceDetection: () => mocks.detect }));
vi.mock("../components/visa-selfie-quality", async (original) => ({
  ...await original<typeof import("../components/visa-selfie-quality")>(),
  encodeVisaJpegUnderLimit: mocks.encode,
  evaluateFinalVisaPhoto: mocks.evaluate,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function setup() {
  const stop = vi.fn();
  const shutdown = { stopStream: stop, stopAnalysis: vi.fn(), waitForLiveAnalysis: vi.fn(), stopCameraAfterAnalysis: vi.fn() };
  const hook = renderHook(() => {
    const state = useVisaCameraState();
    return { state, capture: useVisaPhotoCapture(state, shutdown) };
  });
  act(() => {
    const state = hook.result.current.state;
    const video = document.createElement("video");
    Object.defineProperties(video, { videoWidth: { value: 640 }, videoHeight: { value: 960 } });
    state.videoRef.current = video;
    state.guideRef.current = document.createElement("div");
    state.captureCanvasRef.current = document.createElement("canvas");
    state.analysisCanvasRef.current = document.createElement("canvas");
    state.captureReadyRef.current = true;
    state.setIsCameraReady(true);
  });
  return { ...hook, stop };
}

beforeEach(() => {
  mocks.capture.mockResolvedValue({ image: {}, width: 640, height: 960, close: vi.fn() });
  mocks.encode.mockResolvedValue({ blob: new Blob(["synthetic"], { type: "image/jpeg" }) });
  mocks.decode.mockResolvedValue({ image: {}, close: vi.fn() });
  mocks.detect.mockResolvedValue([]);
  mocks.evaluate.mockReturnValue({ outcome: "pass" });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic");
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: vi.fn(), getImageData: () => ({ data: new Uint8ClampedArray(4) }),
  } as unknown as CanvasRenderingContext2D);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); });

it.each(["encoding", "decode", "inference"] as const)("discards an unmounted capture finishing %s, while closing decoded resources", async (stage) => {
  const finish = deferred<unknown>();
  const decoded = { image: {}, close: vi.fn() };
  if (stage === "encoding") mocks.encode.mockReturnValue(finish.promise);
  if (stage === "decode") mocks.decode.mockReturnValue(finish.promise);
  if (stage === "inference") {
    mocks.decode.mockResolvedValue(decoded);
    mocks.detect.mockReturnValue(finish.promise);
  }
  const hook = setup();
  let capture!: Promise<void>;
  act(() => { capture = hook.result.current.capture(); });
  const pending = stage === "encoding" ? mocks.encode : stage === "decode" ? mocks.decode : mocks.detect;
  await waitFor(() => expect(pending).toHaveBeenCalledOnce());
  hook.unmount();
  await act(async () => {
    finish.resolve(stage === "encoding" ? { blob: new Blob(["synthetic"]) } : stage === "decode" ? decoded : []);
    await capture;
  });
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(mocks.evaluate).not.toHaveBeenCalled();
  expect(hook.stop).not.toHaveBeenCalled();
  if (stage !== "encoding") expect(decoded.close).toHaveBeenCalledOnce();
});

it("a replacement camera owns its state when an old final inference finishes", async () => {
  const inference = deferred<unknown[]>();
  const decoded = { image: {}, close: vi.fn() };
  mocks.decode.mockResolvedValue(decoded);
  mocks.detect.mockReturnValue(inference.promise);
  const hook = setup();
  let capture!: Promise<void>;
  act(() => { capture = hook.result.current.capture(); });
  await waitFor(() => expect(mocks.detect).toHaveBeenCalledOnce());
  act(() => {
    hook.result.current.state.captureLifecycle.invalidate();
    hook.result.current.state.setIsProcessing(false);
    hook.result.current.state.captureStartedRef.current = false;
  });
  await act(async () => { inference.resolve([]); await capture; });
  expect(decoded.close).toHaveBeenCalledOnce();
  expect(hook.stop).not.toHaveBeenCalled();
  expect(hook.result.current.state.capturedPreview).toBeNull();
  expect(hook.result.current.state.isCameraReady).toBe(true);
  expect(hook.result.current.state.processingError).toBeNull();
});

it("publishes only the finished validation after closing both image sources", async () => {
  const sourceClose = vi.fn(), decodedClose = vi.fn();
  const inference = deferred<unknown[]>();
  const validation = { outcome: "hard_failure", message: "Synthetic multiple faces" };
  mocks.capture.mockResolvedValue({ image: {}, width: 640, height: 960, close: sourceClose });
  mocks.decode.mockResolvedValue({ image: {}, close: decodedClose });
  mocks.evaluate.mockReturnValue(validation);
  mocks.detect.mockReturnValue(inference.promise);
  const hook = setup();
  let capture!: Promise<void>;
  act(() => { capture = hook.result.current.capture(); });
  await waitFor(() => expect(mocks.detect).toHaveBeenCalledOnce());
  expect(hook.stop).not.toHaveBeenCalled();
  expect(decodedClose).not.toHaveBeenCalled();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  await act(async () => { inference.resolve([]); await capture; });
  expect(sourceClose).toHaveBeenCalledOnce();
  expect(decodedClose).toHaveBeenCalledOnce();
  expect(hook.stop).toHaveBeenCalledOnce();
  expect(hook.result.current.state.finalValidation).toEqual(validation);
  expect(hook.result.current.state.capturedFile).toBeInstanceOf(File);
  expect(hook.result.current.state.isProcessing).toBe(false);
});
