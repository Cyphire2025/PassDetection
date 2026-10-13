import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { Blob as NodeBlob } from "node:buffer";
import { describe, expect, it, vi } from "vitest";
import apiClient from "./client";

const { stepUp } = vi.hoisted(() => ({ stepUp: vi.fn() }));
vi.mock("@/features/auth/services/step-up-coordinator", () => ({ requestAuthenticationStepUp: stepUp }));
vi.mock("@/features/auth/services/refresh-coordinator", () => ({ readRefreshEpoch: () => "synthetic" }));

describe("returning proof errors", () => {
  it.each(["detail", "error"])("decodes a protected blob %s failure while retaining cookie scope, cancellation and retry advice", async (envelope) => {
    vi.stubGlobal("Blob", NodeBlob);
    const controller = new AbortController();
    const post = vi.spyOn(axios, "post");
    const adapter = (config: InternalAxiosRequestConfig) => {
      expect(config.withCredentials).toBe(true);
      expect(config.signal).toBe(controller.signal);
      expect(config.responseType).toBe("blob");
      return Promise.reject(new AxiosError("Unavailable", "ERR_BAD_RESPONSE", config, undefined, {
        data: new NodeBlob([JSON.stringify({ [envelope]: { code: "verification_cooldown", message: "Please wait before trying again." } })], { type: "application/json" }),
        status: 429, statusText: "Too Many Requests", headers: new AxiosHeaders({ "retry-after": "30" }), config,
      }));
    };
    try {
      await expect(apiClient.get("/api/v1/returning/documents/synthetic-asset", { responseType: "blob", signal: controller.signal, adapter })).rejects.toMatchObject({ status: 429, code: "verification_cooldown", message: "Please wait before trying again.", retryAfterMs: 30_000 });
      expect(post).not.toHaveBeenCalled();
      expect(stepUp).not.toHaveBeenCalled();
    } finally { post.mockRestore(); vi.unstubAllGlobals(); }
  });
  it.each([401, 403])("does not refresh or step up a staff session for public proof status %s", async (status) => {
    const post = vi.spyOn(axios, "post");
    const code = status === 403 ? "STEP_UP_REQUIRED" : "PROOF_EXPIRED";
    const adapter = (config: InternalAxiosRequestConfig) => Promise.reject(new AxiosError("Proof unavailable", "ERR_BAD_RESPONSE", config, undefined, { data: { error: { code, message: "Verify again or upload current documents." } }, status, statusText: "Denied", headers: new AxiosHeaders(), config }));
    await expect(apiClient.post("/api/v1/returning/passport", {}, { adapter })).rejects.toMatchObject({ status, code });
    expect(post).not.toHaveBeenCalled();
    expect(stepUp).not.toHaveBeenCalled();
    post.mockRestore();
  });
});
