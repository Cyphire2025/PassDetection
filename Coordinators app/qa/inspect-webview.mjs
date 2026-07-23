const endpoint = process.env.COORDINATOR_CDP_ENDPOINT ?? "http://localhost:9222";
const verifyCamera = process.argv.includes("--camera");

const targets = await fetch(`${endpoint}/json`).then((response) => response.json());
const target = targets.find((candidate) => candidate.type === "page");
if (!target?.webSocketDebuggerUrl) {
  throw new Error("No debuggable coordinator WebView page was found.");
}

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let nextCommandId = 1;
function evaluate(expression, timeoutMilliseconds = 20_000) {
  const commandId = nextCommandId;
  nextCommandId += 1;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error(`CDP evaluation timed out: ${commandId}`)),
      timeoutMilliseconds,
    );
    const handleMessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== commandId) return;
      clearTimeout(timeout);
      socket.removeEventListener("message", handleMessage);
      if (message.error || message.result?.exceptionDetails) {
        reject(new Error(JSON.stringify(message.error ?? message.result.exceptionDetails)));
        return;
      }
      resolve(message.result?.result?.value);
    };
    socket.addEventListener("message", handleMessage);
    socket.send(JSON.stringify({
      id: commandId,
      method: "Runtime.evaluate",
      params: {
        expression,
        awaitPromise: true,
        returnByValue: true,
      },
    }));
  });
}

const baseEvidence = await evaluate(`(async () => {
  const registrations = "serviceWorker" in navigator
    ? await navigator.serviceWorker.getRegistrations()
    : [];
  return {
    title: document.title,
    origin: location.origin,
    path: location.pathname,
    secureContext: window.isSecureContext,
    serviceWorkerSupported: "serviceWorker" in navigator,
    serviceWorkerScopes: registrations.map((registration) => registration.scope),
    mediaDevicesAvailable: Boolean(navigator.mediaDevices),
    getUserMediaAvailable: Boolean(navigator.mediaDevices?.getUserMedia),
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
  };
})()`);

let cameraEvidence = null;
if (verifyCamera) {
  cameraEvidence = await evaluate(`(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    try {
      const [track] = stream.getVideoTracks();
      return {
        acquired: Boolean(track),
        readyState: track?.readyState ?? null,
        muted: track?.muted ?? null,
        settings: track?.getSettings?.() ?? null,
      };
    } finally {
      stream.getTracks().forEach((track) => track.stop());
    }
  })()`, 60_000);
}

socket.close();
console.log(JSON.stringify({ page: baseEvidence, camera: cameraEvidence }, null, 2));
