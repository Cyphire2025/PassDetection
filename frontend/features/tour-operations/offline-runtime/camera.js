import { getCameraErrorMessage } from './messages.js';

export function createOfflineCamera(state, view, handleDecode) {
  const { elements, getSelectedSession, setFeedback } = view;

  let scannerControls = null;

  let codeReader = null;

  let cameraStarting = false;

  let cameraGeneration = 0;

  async function startCamera() {
    if (cameraStarting || scannerControls) return;
    if (!state.ownerUserId || !getSelectedSession()) {
      setFeedback("Select a cached group and activity first.", "error");
      return;
    }
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setFeedback(
        "Camera access is unavailable. Reopen this page from the secure coordinator app.",
        "error",
      );
      return;
    }
    if (!window.ZXingBrowser?.BrowserQRCodeReader) {
      setFeedback("The offline QR scanner did not load. Reconnect and reopen coordinator.", "error");
      return;
    }
  
    stopCamera("");
    const generation = cameraGeneration;
    cameraStarting = true;
    elements.startButton.disabled = true;
    elements.stopButton.disabled = false;
    elements.placeholder.hidden = true;
    setFeedback("Starting camera...", "info");
  
    try {
      codeReader = new window.ZXingBrowser.BrowserQRCodeReader(undefined, {
        delayBetweenScanSuccess: 700,
        delayBetweenScanAttempts: 100,
        tryPlayVideoTimeout: 5_000,
      });
      const controls = await codeReader.decodeFromConstraints(
        {
          audio: false,
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 960, max: 1280 },
            height: { ideal: 540, max: 720 },
            frameRate: { ideal: 24, max: 30 },
          },
        },
        elements.preview,
        handleDecode,
      );
      if (generation !== cameraGeneration || document.hidden) {
        controls.stop();
        releaseCameraStreams();
        return;
      }
      scannerControls = controls;
      setFeedback("Camera ready. Hold a passenger QR inside the frame.", "info");
    } catch (error) {
      if (generation !== cameraGeneration) return;
      stopCamera("");
      setFeedback(getCameraErrorMessage(error), "error");
    } finally {
      cameraStarting = false;
      elements.startButton.disabled = Boolean(scannerControls) || !getSelectedSession();
    }
  }

  function stopCamera(message) {
    cameraGeneration += 1;
    try {
      scannerControls?.stop();
    } catch {
      // Camera teardown is best-effort across mobile browser implementations.
    }
    scannerControls = null;
    releaseCameraStreams();
    codeReader = null;
    elements.startButton.disabled = cameraStarting || !getSelectedSession();
    elements.stopButton.disabled = true;
    elements.placeholder.hidden = false;
    if (message) setFeedback(message, "info");
  }

  function releaseCameraStreams() {
    try {
      window.ZXingBrowser?.BrowserCodeReader?.releaseAllStreams();
    } catch {
      // Also stop the element stream below for browsers with partial controls.
    }
    const stream = elements.preview.srcObject;
    if (stream && typeof stream.getTracks === "function") {
      for (const track of stream.getTracks()) track.stop();
    }
    elements.preview.srcObject = null;
  }

  return { startCamera, stopCamera };
}
