import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VisaSelfieCamera } from "./visa-selfie-camera";

const mocks = vi.hoisted(() => ({
  capture: vi.fn(),
  drain: vi.fn(),
  media: vi.fn(),
  encode: vi.fn(),
}));

vi.mock("../services/visa-face-detection-loader", () => ({
  loadVisaFaceDetection: vi.fn().mockRejectedValue(new Error("Synthetic unavailable model")),
  initializeVisaFaceDetection: vi.fn(),
}));
vi.mock("../services/camera-capture", async (original) => ({
  ...await original<typeof import("../services/camera-capture")>(),
  captureBestCameraSource: mocks.capture,
}));
vi.mock("../services/visa-selfie-runtime", async (original) => ({
  ...await original<typeof import("../services/visa-selfie-runtime")>(),
  waitForVisaInferenceDrain: mocks.drain,
}));
vi.mock("./visa-selfie-quality", async (original) => ({
  ...await original<typeof import("./visa-selfie-quality")>(),
  encodeVisaJpegUnderLimit: mocks.encode,
}));

function stream() {
  const stop = vi.fn();
  const track = { stop, getSettings: () => ({ facingMode: "user" }) };
  return {
    value: { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream,
    stop,
  };
}

describe("Visa camera resource ownership", () => {
  beforeEach(() => {
    mocks.drain.mockResolvedValue(true);
    vi.stubGlobal("isSecureContext", true);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true, value: { getUserMedia: mocks.media },
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(async () => {
    cleanup();
    await act(async () => undefined);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.resetAllMocks();
  });

  it("closes the captured still when the canvas cannot provide a drawing context", async () => {
    const camera = stream();
    const close = vi.fn();
    mocks.media.mockResolvedValue(camera.value);
    mocks.capture.mockResolvedValue({ image: {}, width: 640, height: 960, close });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = render(<VisaSelfieCamera onCapture={vi.fn()} onCancel={vi.fn()} />);
    const video = container.querySelector("video")!;
    Object.defineProperties(video, {
      videoWidth: { configurable: true, value: 640 },
      videoHeight: { configurable: true, value: 960 },
    });
    await waitFor(() => expect(video.srcObject).toBe(camera.value));
    fireEvent.loadedData(video);
    const capture = await screen.findByRole("button", { name: "Capture with guided fallback" });
    expect(capture).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(capture).toBeEnabled();
    fireEvent.click(capture);
    await screen.findByText("This browser cannot capture a camera image.");
    await waitFor(() => expect(mocks.capture).toHaveBeenCalledOnce());
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(screen.queryByRole("button", { name: "Use Visa Photo" })).not.toBeInTheDocument();
  });

  it("finishing an old camera drain stops its own tracks without detaching the replacement", async () => {
    const previous = stream();
    const replacement = stream();
    mocks.media.mockResolvedValueOnce(previous.value).mockResolvedValue(replacement.value);
    const { container } = render(<VisaSelfieCamera onCapture={vi.fn()} onCancel={vi.fn()} />);
    const video = container.querySelector("video")!;
    await waitFor(() => expect(video.srcObject).toBe(previous.value));
    let finishDrain!: (drained: boolean) => void;
    const draining = new Promise<boolean>((resolve) => { finishDrain = resolve; });
    mocks.drain.mockReturnValue(draining);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    fireEvent(document, new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(video.srcObject).toBe(replacement.value));
    await act(async () => { finishDrain(true); });
    expect(previous.stop).toHaveBeenCalled();
    expect(replacement.stop).not.toHaveBeenCalled();
    expect(video.srcObject).toBe(replacement.value);
  });

  it.each(["close", "restart"])("releases a late captured still after %s without encoding or replacing the current camera", async (action) => {
    const camera = stream();
    const replacement = stream();
    const close = vi.fn();
    let finishCapture!: (source: unknown) => void;
    mocks.capture.mockImplementation(() => new Promise((resolve) => { finishCapture = resolve; }));
    mocks.encode.mockRejectedValue(new Error("Unexpected stale encoding"));
    mocks.media.mockResolvedValueOnce(camera.value).mockResolvedValue(replacement.value);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
    const onCapture = vi.fn();
    const { container, unmount } = render(<VisaSelfieCamera onCapture={onCapture} onCancel={vi.fn()} />);
    const video = container.querySelector("video")!;
    Object.defineProperties(video, {
      videoWidth: { configurable: true, value: 640 },
      videoHeight: { configurable: true, value: 960 },
    });
    await waitFor(() => expect(video.srcObject).toBe(camera.value));
    fireEvent.loadedData(video);
    await screen.findByRole("button", { name: "Capture with guided fallback" });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Capture with guided fallback" }));
    await waitFor(() => expect(mocks.capture).toHaveBeenCalledOnce());
    if (action === "close") unmount();
    else {
      Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
      fireEvent(document, new Event("visibilitychange"));
      Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
      fireEvent(document, new Event("visibilitychange"));
      await waitFor(() => expect(video.srcObject).toBe(replacement.value));
    }
    await act(async () => { finishCapture({ image: {}, width: 640, height: 960, close }); });
    expect(close).toHaveBeenCalledOnce();
    expect(mocks.encode).not.toHaveBeenCalled();
    expect(onCapture).not.toHaveBeenCalled();
    if (action === "restart") {
      expect(video.srcObject).toBe(replacement.value);
      expect(replacement.stop).not.toHaveBeenCalled();
    }
  });
});
