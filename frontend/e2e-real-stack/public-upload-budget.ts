import { setTimeout as pause } from "node:timers/promises";
import type { APIRequestContext } from "@playwright/test";

// The three serial browser projects share one proxy IP and its real 60/minute
// API bucket. Each full journey uses ~32 requests, plus autosave/cleanup margin.
const JOURNEY_REQUESTS = 40;

export async function waitForPublicUploadBudget(request: APIRequestContext, token: string): Promise<void> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const response = await request.get("/api/v1/returning/capabilities", { params: { group_token: token } });
    const headers = response.headers();
    let wait: number;
    if (response.status() === 429) {
      const body = await response.json();
      const seconds = Number(headers["retry-after"]);
      if (body.error?.code !== "APP_RATE_LIMITED" || !Number.isFinite(seconds) || seconds < 1 || seconds > 60) {
        throw new Error("Unexpected qualification rate-limit response; refusing to bypass it");
      }
      wait = seconds * 1000 + 250;
    } else {
      const remaining = Number(headers["x-ratelimit-remaining"]);
      const date = Date.parse(headers.date);
      if (response.status() !== 200 || headers["x-ratelimit-policy"] !== "api" || !Number.isFinite(remaining) || !Number.isFinite(date)) {
        throw new Error("Qualification API quota metadata is unavailable");
      }
      if (remaining >= JOURNEY_REQUESTS) return;
      // Use the server's clock, not the runner's, for its fixed minute window.
      wait = 60_000 - date % 60_000 + 250;
    }
    if (attempt === 1) throw new Error("Qualification API budget did not recover after one window");
    await pause(wait);
  }
}
