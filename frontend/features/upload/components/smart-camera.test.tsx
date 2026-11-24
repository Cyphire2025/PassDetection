import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SmartCamera } from "./smart-camera";

const mocks = vi.hoisted(() => ({ normalize: vi.fn(), validate: vi.fn(), media: vi.fn(), capture: vi.fn() }));
vi.mock("../hooks/use-passport-frame-detection", () => ({ usePassportFrameDetection: () => ({ isDetected: true, status: "ready", hasDocumentCandidate: true, lightingStatus: "good" }) }));
vi.mock("../services/passport-perspective-correction", () => ({ normalizePassportCanvasCapture: mocks.normalize }));
vi.mock("../services/passport-final-quality", () => ({ validatePassportFinalFile: mocks.validate }));
vi.mock("../services/camera-capture", async (original) => ({
  ...await original<typeof import("../services/camera-capture")>(), captureBestCameraSource: mocks.capture,
}));

function stream() {
  const stop = vi.fn();
  return { stop, value: { getTracks: () => [{ stop }] } as unknown as MediaStream };
}
beforeEach(() => {
  vi.stubGlobal("isSecureContext", true);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: mocks.media } });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
});

async function readyCamera() {
  const activeStream = stream();
  mocks.media.mockResolvedValue(activeStream.value);
  const file = new File(["synthetic"], "passport.jpg", { type: "image/jpeg" });
  mocks.normalize.mockResolvedValue({ file });
  const release = vi.fn();
  mocks.capture.mockResolvedValue({ image: {}, width: 1440, height: 990, close: release });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic");
  const onCapture = vi.fn();
  const rendered = render(<SmartCamera pageSide="front" onCapture={onCapture} onCancel={vi.fn()} />);
  const video = rendered.container.querySelector("video")!;
  Object.defineProperties(video, { videoWidth: { configurable: true, value: 1440 }, videoHeight: { configurable: true, value: 990 } });
  await waitFor(() => expect(video.srcObject).toBe(activeStream.value));
  fireEvent.loadedData(video);
  return { ...rendered, file, release, onCapture, activeStream };
}

it.each(["pass", "borderline", "hard_failure"])("preserves the exact outgoing file and %s acceptance gate", async outcome => {
  mocks.validate.mockResolvedValue({ outcome, message: "Quality result", confirmationPrompt: "I confirm the details are legible" });
  const camera = await readyCamera();
  fireEvent.click(screen.getByRole("button", { name: "Capture passport page" }));
  await screen.findByAltText("Captured passport front page");
  expect(mocks.validate).toHaveBeenCalledWith(camera.file, "front");
  expect(camera.release).toHaveBeenCalledOnce();
  expect(camera.activeStream.stop).toHaveBeenCalledOnce();
  if (outcome === "hard_failure") {
    expect(screen.queryByRole("button", { name: "Use Photo" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retake" })).toBeEnabled();
    expect(camera.onCapture).not.toHaveBeenCalled();
    return;
  }
  const accept = screen.getByRole("button", { name: "Use Photo" });
  if (outcome === "borderline") {
    expect(accept).toBeDisabled();
    fireEvent.click(accept);
    expect(camera.onCapture).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: "I confirm the details are legible" }));
  }
  fireEvent.click(accept);
  expect(camera.onCapture).toHaveBeenCalledExactlyOnceWith(camera.file);
});

it("does not allocate or publish a preview when exact-file validation completes after unmount", async () => {
  let finish!: (result: unknown) => void;
  mocks.validate.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const camera = await readyCamera();
  fireEvent.click(screen.getByRole("button", { name: "Capture passport page" }));
  await waitFor(() => expect(mocks.validate).toHaveBeenCalledOnce());
  camera.unmount();
  await act(async () => { finish({ outcome: "pass" }); });
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(camera.onCapture).not.toHaveBeenCalled();
  expect(camera.release).toHaveBeenCalledOnce();
});

it("admits one capture while the high-resolution source is pending", async () => {
  let finish!: (result: unknown) => void;
  mocks.validate.mockResolvedValue({ outcome: "pass" });
  const camera = await readyCamera();
  mocks.capture.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const button = screen.getByRole("button", { name: "Capture passport page" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(mocks.capture).toHaveBeenCalledOnce();
  await act(async () => { finish({ image: {}, width: 1440, height: 990, close: camera.release }); });
  await screen.findByAltText("Captured passport front page");
  expect(mocks.normalize).toHaveBeenCalledOnce();
  expect(camera.release).toHaveBeenCalledOnce();
});

it("stops a camera lease granted after its surface unmounts", async () => {
  let finish!: (value: MediaStream) => void;
  const lateStream = stream();
  mocks.media.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const camera = render(<SmartCamera pageSide="front" onCapture={vi.fn()} onCancel={vi.fn()} />);
  await waitFor(() => expect(mocks.media).toHaveBeenCalledOnce());
  camera.unmount();
  await act(async () => { finish(lateStream.value); });
  expect(lateStream.stop).toHaveBeenCalledOnce();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.resetAllMocks(); });

it.each(["unmount", "restart"])("ignores a capture normalized after %s without stopping the replacement or allocating a preview", async (action) => {
  const previous = stream(), replacement = stream();
  let finish!: (result: unknown) => void;
  mocks.normalize.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  mocks.validate.mockResolvedValue({ outcome: "pass" });
  mocks.capture.mockResolvedValue({ image: {}, width: 1440, height: 990, close: vi.fn() });
  mocks.media.mockResolvedValueOnce(previous.value).mockResolvedValue(replacement.value);
  const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:synthetic");
  const onCapture = vi.fn();
  const { container, unmount } = render(<SmartCamera pageSide="front" onCapture={onCapture} onCancel={vi.fn()} />);
  const video = container.querySelector("video")!;
  Object.defineProperties(video, { videoWidth: { configurable: true, value: 1440 }, videoHeight: { configurable: true, value: 990 } });
  await waitFor(() => expect(video.srcObject).toBe(previous.value));
  fireEvent.loadedData(video);
  fireEvent.click(container.querySelector('button[aria-label="Capture passport page"]')!);
  await waitFor(() => expect(mocks.normalize).toHaveBeenCalledOnce());
  if (action === "unmount") unmount();
  else {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    fireEvent(document, new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(video.srcObject).toBe(replacement.value));
  }
  await act(async () => { finish({ file: new File(["synthetic"], "passport.jpg", { type: "image/jpeg" }) }); });
  expect(mocks.validate).not.toHaveBeenCalled();
  expect(createUrl).not.toHaveBeenCalled();
  expect(onCapture).not.toHaveBeenCalled();
  if (action === "restart") {
    expect(video.srcObject).toBe(replacement.value);
    expect(replacement.stop).not.toHaveBeenCalled();
  }
});
