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

/** Only external message delivery is substituted. The real API verifies and consumes this DB proof. */
export async function installSyntheticOtpDelivery(page: Page): Promise<void> {
  await page.route("**/api/v1/passports/*/contact-otp/request", async (route) => {
    const request = route.request();
    const submission = new URL(request.url()).pathname.split("/").at(-3);
    const result = execFileSync("docker", [
      "compose", "--env-file", "../.env.example", "-p", "passdetection-qualification",
      "-f", "../docker-compose.qualification.yml", "exec", "-T", "backend", "python",
      "/workspace/scripts/qa/browser_workflow_fixtures.py",
    ], {
      cwd: process.cwd(), encoding: "utf8", timeout: 15_000,
      input: JSON.stringify({ ...request.postDataJSON(), submission_id: submission, session_id: request.headers()["x-upload-session-id"] }),
    });
    const response = result.trim().split(/\r?\n/).at(-1)!;
    JSON.parse(response);
    await route.fulfill({ status: 200, contentType: "application/json", body: response });
  });
}

/** Synthetic video frames at getUserMedia only: real video, ZXing decoder and queue remain in use. */
export async function installCameraFrames(page: Page, payload: string): Promise<() => Promise<void>> {
  const qr = await QRCode.toDataURL(payload, { width: 480, margin: 4, errorCorrectionLevel: "M" });
  const install = ({ qr }: { qr: string }) => {
    if (Object.hasOwn(navigator.mediaDevices, "getUserMedia") && Object.hasOwn(window, "qualificationCameraFrame")) return;
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
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", { value: async () => {
      try {
        const stream = canvas.captureStream(20);
        Object.defineProperty(window, "qualificationCameraSource", { configurable: true, value: { tracks: stream.getTracks().map((track) => ({ kind: track.kind, readyState: track.readyState })) } });
        return stream;
      } catch (error) {
        Object.defineProperty(window, "qualificationCameraSource", { configurable: true, value: { error: error instanceof Error ? error.name : "unknown" } });
        throw error;
      }
    } });
    Object.defineProperty(navigator.mediaDevices, "enumerateDevices", { value: async () => [] });
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
