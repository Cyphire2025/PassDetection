import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import QRCode from "qrcode";

type Seed = {
  group_id: string; session_id: string;
  browser_workflows: Record<string, { email: string; password: string; qr_payload: string; public_token: string; session_id: string }>;
};

export function browserSeed(): Seed {
  const content = readFileSync(path.resolve(process.cwd(), "../outputs/qualification/seed.log"), "utf8");
  const line = content.split(/\r?\n/).findLast((entry) => entry.trim().startsWith("{\""));
  if (!line) throw new Error("Run the isolated current seed before the real browser suite");
  return JSON.parse(line) as Seed;
}

async function freshFixture(page: Page, token: string, session: string, operation: string, fields: Record<string, string> = {}) {
  const cookie = (await page.context().cookies(`${new URL(page.url()).origin}/api/v1/public-drafts/${token}`))
    .find((value) => value.name === "pd_fresh_drafts");
  if (!cookie || !session) throw new Error("The real fresh draft capability is required");
  const result = execFileSync("docker", [
      "compose", "--env-file", "../.env.example", "-p", "passdetection-qualification",
      "-f", "../docker-compose.qualification.yml", "exec", "-T", "backend", "python",
      "/workspace/scripts/qa/browser_workflow_fixtures.py",
  ], {
    cwd: process.cwd(), encoding: "utf8", timeout: 15_000,
    input: JSON.stringify({ ...fields, operation, group_token: token, session_id: session, browser_secret: cookie.value }),
  });
  return JSON.parse(result.trim().split(/\r?\n/).at(-1)!);
}

/** Capture only delivery; actual draft authorization, challenge creation and quotas still run. */
export async function installSyntheticOtpDelivery(page: Page): Promise<() => string> {
  let delivered: string | undefined;
  await page.route("**/api/v1/public-drafts/*/contact/request", async (route) => {
    const request = route.request(), body = request.postDataJSON();
    const token = new URL(request.url()).pathname.split("/").at(-3)!;
    if (body.group_token !== token) throw new Error("Contact request must match its draft group");
    const result = await freshFixture(page, token, request.headers()["x-upload-session-id"], "request_contact", body);
    delivered = result.delivered_code;
    await route.fulfill({ status: 200, json: result.response });
  });
  return () => { if (!delivered) throw new Error("No synthetic OTP was delivered"); return delivered; };
}

export async function inspectPublishedUpload(page: Page, token: string, session: string, source: string) {
  return freshFixture(page, token, session, "inspect_publication", { source_submission_id: source });
}

/** Synthetic video frames at getUserMedia only: real video, ZXing decoder and queue remain in use. */
export async function installCameraFrames(page: Page, payload: string): Promise<() => Promise<void>> {
  const qr = await QRCode.toDataURL(payload, { width: 480, margin: 4, errorCorrectionLevel: "M" });
  const install = ({ qr }: { qr: string }) => {
    if (Object.hasOwn(navigator.mediaDevices, "getUserMedia") && Object.hasOwn(window, "qualificationCameraFrame")) return;
    // Keep the native wrapper reachable. WebKit can collect a wrapper with
    // expando overrides even while its underlying MediaDevices stays alive.
    const mediaDevices = navigator.mediaDevices;
    Object.defineProperty(window, "qualificationMediaDevices", { value: mediaDevices });
    const canvas = document.createElement("canvas"); canvas.width = 640; canvas.height = 480;
    const context = canvas.getContext("2d")!;
    const image = new Image(); image.src = qr;
    let showQr = false;
    Object.defineProperty(window, "qualificationCameraFrame", { value: (visible: boolean) => { showQr = visible; } });
    const draw = () => {
      context.fillStyle = "white"; context.fillRect(0, 0, canvas.width, canvas.height);
      if (showQr && image.complete) context.drawImage(image, 80, 0, 480, 480);
    };
    draw(); window.setInterval(draw, 50);
    Object.defineProperty(mediaDevices, "getUserMedia", { value: async () => {
      try {
        const stream = canvas.captureStream(20);
        Object.defineProperty(window, "qualificationCameraSource", { configurable: true, value: { tracks: stream.getTracks().map((track) => ({ kind: track.kind, readyState: track.readyState })) } });
        return stream;
      } catch (error) {
        Object.defineProperty(window, "qualificationCameraSource", { configurable: true, value: { error: error instanceof Error ? error.name : "unknown" } });
        throw error;
      }
    } });
    Object.defineProperty(mediaDevices, "enumerateDevices", { value: async () => [] });
  };
  await page.addInitScript(install, { qr });
  return async () => { await page.evaluate(install, { qr }); };
}

export async function cameraFrame(page: Page, visible: boolean): Promise<void> {
  await page.evaluate((value) => (window as unknown as { qualificationCameraFrame: (shown: boolean) => void }).qualificationCameraFrame(value), visible);
}

export async function syntheticCover(page: Page): Promise<Buffer> {
  const encoded = await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 900; canvas.height = 600;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#192d4b"; context.fillRect(0, 0, 900, 600);
    context.fillStyle = "white"; context.font = "36px sans-serif";
    context.fillText("SYNTHETIC QUALIFICATION COVER", 50, 300);
    return canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
  });
  return Buffer.from(encoded, "base64");
}
