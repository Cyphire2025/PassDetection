import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { authApi } from "./auth.api";
import { installBrowserLocks } from "@/test-support/browser-locks";

const initialAdapter = apiClient.defaults.adapter;
const commands = [
  ["login", () => authApi.login({ email: "a@example.test", password: "SyntheticPass1" })],
  ["activation", () => authApi.activate("synthetic-token", "SyntheticPass1")],
  ["recovery", () => authApi.completePasswordRecovery("synthetic-token", "SyntheticPass1")],
  ["MFA", () => authApi.verifyMfa("synthetic-challenge", "123456")],
] as const;

describe("identity HTTP cancellation", () => {
  let locks: ReturnType<typeof installBrowserLocks>;
  beforeEach(() => {
    locks = installBrowserLocks();
    useAuthStore.setState({ user: null, sessionVersion: 0, isAuthenticated: false });
  });
  afterEach(() => { locks.restore(); apiClient.defaults.adapter = initialAdapter; vi.restoreAllMocks(); });

  it.each(commands)("aborts old %s before delayed response headers when B becomes current", async (_name, command) => {
    let request!: InternalAxiosRequestConfig;
    const aborted = vi.fn();
    apiClient.defaults.adapter = async (config) => {
      request = config;
      return new Promise((_resolve, reject) => config.signal?.addEventListener?.("abort", () => {
        aborted(); reject(new Error("Synthetic delayed connection aborted"));
      }));
    };
    const pending = command();
    const rejected = expect(pending).rejects.toBeDefined();
    await Promise.resolve();
    expect(request.signal?.aborted).toBe(false);
    useAuthStore.setState({ user: { id: "owner-b" } as User, sessionVersion: 1, isAuthenticated: true });
    expect(request.signal?.aborted).toBe(true);
    await rejected;
    expect(aborted).toHaveBeenCalledOnce();
    expect(useAuthStore.getState().user?.id).toBe("owner-b");
  });

  it.each(commands)("allows normal %s and detaches cancellation after the response", async (_name, command) => {
    let request!: InternalAxiosRequestConfig;
    apiClient.defaults.adapter = async (config) => {
      request = config;
      return { data: { status: "authenticated", user: { id: "owner-a" } }, status: 200, statusText: "OK", headers: new AxiosHeaders(), config };
    };
    await expect(command()).resolves.toHaveProperty("user.id", "owner-a");
    useAuthStore.setState({ user: { id: "owner-a" } as User, sessionVersion: 1 });
    expect(request.signal?.aborted).toBe(false);
  });
});
