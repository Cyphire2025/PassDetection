import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { describe, expect, it, vi } from "vitest";
import apiClient from "./client";

const { stepUp } = vi.hoisted(() => ({ stepUp: vi.fn() }));
vi.mock("@/features/auth/services/step-up-coordinator", () => ({ requestAuthenticationStepUp: stepUp }));
vi.mock("@/features/auth/services/refresh-coordinator", () => ({ readRefreshEpoch: () => "synthetic" }));

describe("returning proof errors", () => {
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
