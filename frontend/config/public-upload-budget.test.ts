import type { APIRequestContext } from "@playwright/test";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setTimeout as pause } from "node:timers/promises";
import { waitForPublicUploadBudget } from "../e2e-real-stack/public-upload-budget";

vi.mock("node:timers/promises", () => {
  const timers = { setTimeout: vi.fn().mockResolvedValue(undefined) };
  return { ...timers, default: timers };
});
const response = (remaining: number, status = 200, code = "APP_RATE_LIMITED") => ({
  status: () => status,
  headers: () => ({ date: "Thu, 22 Oct 2026 22:04:55 GMT", "x-ratelimit-policy": "api", "x-ratelimit-remaining": String(remaining), "retry-after": "5" }),
  json: async () => ({ error: { code } }),
});
const request = (...responses: ReturnType<typeof response>[]) => {
  const get = vi.fn();
  for (const result of responses) get.mockResolvedValueOnce(result);
  return { get, context: { get } as unknown as APIRequestContext };
};

beforeEach(() => vi.clearAllMocks());

describe("shared real-stack public API quota", () => {
  it("runs immediately when the real remaining budget covers the full journey", async () => {
    const api = request(response(52));
    await waitForPublicUploadBudget(api.context, "synthetic-trip");
    expect(api.get).toHaveBeenCalledWith("/api/v1/returning/capabilities", { params: { group_token: "synthetic-trip" } });
    expect(pause).not.toHaveBeenCalled();
  });

  it("lets preceding browser traffic expire using the server minute before starting mutations", async () => {
    const api = request(response(13), response(59));
    await waitForPublicUploadBudget(api.context, "synthetic-trip");
    expect(pause).toHaveBeenCalledExactlyOnceWith(5250);
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("honors a real API Retry-After without accepting the rejected request as success", async () => {
    const api = request(response(0, 429), response(59));
    await waitForPublicUploadBudget(api.context, "synthetic-trip");
    expect(pause).toHaveBeenCalledExactlyOnceWith(5250);
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("does not retry another security quota or hide a persistently exhausted budget", async () => {
    await expect(waitForPublicUploadBudget(request(response(0, 429, "verification_cooldown")).context, "trip"))
      .rejects.toThrow("Unexpected qualification rate-limit response");
    expect(pause).not.toHaveBeenCalled();
    await expect(waitForPublicUploadBudget(request(response(13), response(0)).context, "trip"))
      .rejects.toThrow("did not recover after one window");
    expect(pause).toHaveBeenCalledTimes(1);
  });
});
