import axios, { AxiosError, AxiosHeaders, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient, { refreshAuthenticatedSession } from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import { installBrowserLocks } from "@/test-support/browser-locks";
import type { User } from "@/types";
import { authApi } from "./auth.api";
import { coordinateCookieMutation } from "../services/cookie-mutation";
import { clearServerSessionCookies } from "../services/session-state";

const stepUp = vi.hoisted(() => vi.fn());
vi.mock("../services/step-up-coordinator", () => ({ requestAuthenticationStepUp: stepUp }));
const originalAdapter = apiClient.defaults.adapter;
const originalRawAdapter = axios.defaults.adapter;
const owner = { id: "owner-a" } as User;
function response(config: InternalAxiosRequestConfig, data: unknown = { status: "authenticated", user: owner }) {
  return { config, data, status: 200, statusText: "OK", headers: new AxiosHeaders() };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => { resolve = finish; });
  return { promise, resolve };
}

describe("cookie-writer HTTP transport boundary", () => {
  let locks: ReturnType<typeof installBrowserLocks>;
  beforeEach(() => {
    locks = installBrowserLocks();
    stepUp.mockReset();
    useAuthStore.setState({ user: owner, sessionVersion: 1, isAuthenticated: true });
  });
  afterEach(() => {
    locks.restore(); apiClient.defaults.adapter = originalAdapter; axios.defaults.adapter = originalRawAdapter;
    vi.restoreAllMocks(); vi.unstubAllGlobals(); window.localStorage.clear();
  });

  it("fails closed without Web Locks while preserving public recovery requests", async () => {
    locks.restore();
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config, { message: "Recovery requested" }));
    apiClient.defaults.adapter = adapter;
    await expect(authApi.login({ email: "a@example.test", password: "SyntheticPass1" }))
      .rejects.toMatchObject({ code: "AUTH_COOKIE_COORDINATION_UNAVAILABLE", message: expect.stringContaining("Use HTTPS or localhost") });
    expect(adapter).not.toHaveBeenCalled();
    await expect(authApi.requestPasswordRecovery("a@example.test")).resolves.toHaveProperty("message", "Recovery requested");
    expect(adapter).toHaveBeenCalledOnce();
  });

  it("allows a later intentional login queued behind an earlier identity action", async () => {
    const first = deferred<ReturnType<typeof response>>();
    const entered = deferred<void>();
    const paths: string[] = [];
    apiClient.defaults.adapter = async (config) => {
      paths.push(config.url!);
      if (paths.length === 1) { entered.resolve(); return first.promise; }
      return response(config);
    };
    const activation = authApi.activate("synthetic-token", "SyntheticPass1");
    await entered.promise;
    const login = authApi.login({ email: "b@example.test", password: "SyntheticPass1" });
    await Promise.resolve();
    expect(paths).toEqual(["/api/v1/auth/activate"]);
    first.resolve(response({} as InternalAxiosRequestConfig));
    await Promise.all([activation, login]);
    expect(paths).toEqual(["/api/v1/auth/activate", "/api/v1/auth/login"]);
  });

  it("releases a cookie-writer lock before a step-up and reacquires it for the retry", async () => {
    const paths: string[] = [];
    apiClient.defaults.adapter = async (config) => {
      paths.push(config.url!);
      if (paths.length === 1) throw new AxiosError("Step up", "ERR_BAD_RESPONSE", config, undefined, {
        ...response(config), status: 403, data: { error: { code: "STEP_UP_REQUIRED" } },
      });
      return response(config);
    };
    stepUp.mockImplementation(() => authApi.stepUp("123456").then(() => undefined));
    await authApi.changePassword("CurrentPass1", "ReplacementPass1");
    expect(paths).toEqual(["/api/v1/auth/password/change", "/api/v1/auth/mfa/step-up", "/api/v1/auth/password/change"]);
  });

  it("cancels an identity request waiting for the lock without dispatching it under B", async () => {
    const held = deferred<void>(); const entered = deferred<void>();
    const holder = coordinateCookieMutation(() => { entered.resolve(); return held.promise; });
    await entered.promise;
    const adapter = vi.fn<AxiosAdapter>(async (config) => response(config));
    apiClient.defaults.adapter = adapter;
    const operation = authApi.activate("synthetic-token", "SyntheticPass1");
    const rejected = expect(operation).rejects.toBeDefined();
    useAuthStore.setState({ user: { id: "owner-b" } as User, sessionVersion: 2 });
    await rejected;
    held.resolve(); await holder;
    expect(adapter).not.toHaveBeenCalled();
  });

  it("binds raw refresh to its initial actor and does not retry an owner conflict", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      expect(config.headers.get("X-Expected-Actor-Id")).toBe("owner-a");
      throw new AxiosError("Owner changed", "ERR_BAD_RESPONSE", config, undefined, {
        ...response(config), status: 409, data: { error: { code: "AUTH_REQUEST_OWNER_CHANGED", message: "Changed" } },
      });
    });
    axios.defaults.adapter = adapter;
    await expect(refreshAuthenticatedSession()).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(adapter).toHaveBeenCalledOnce();
  });

  it.each(["/api/v1/auth/activate", "/api/v1/auth/mfa/verify", "/api/v1/auth/password/recovery/complete"])(
    "preserves the identity proof failure without attempting staff refresh: %s", async (url) => {
      const raw = vi.spyOn(axios, "post");
      const adapter: AxiosAdapter = async (config) => {
        throw new AxiosError("Invalid proof", "ERR_BAD_RESPONSE", config, undefined, {
          ...response(config), status: 401, data: { error: { code: "INVALID_IDENTITY_PROOF", message: "Expired" } },
        });
      };
      await expect(apiClient.post(url, {}, { adapter })).rejects.toMatchObject({ code: "INVALID_IDENTITY_PROOF" });
      expect(raw).not.toHaveBeenCalled();
    },
  );

  it("carries the initiating logout actor even after local identity was cleared", async () => {
    useAuthStore.setState({ user: null, sessionVersion: 2, isAuthenticated: false });
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 409 }));
    vi.stubGlobal("fetch", fetch);
    await clearServerSessionCookies("owner-a");
    expect(fetch).toHaveBeenCalledWith("/api/v1/auth/logout", expect.objectContaining({
      headers: { "X-Expected-Actor-Id": "owner-a" }, credentials: "include", method: "POST",
    }));
  });

  it("does not require browser locking for nonbrowser operations", async () => {
    vi.stubGlobal("window", undefined);
    await expect(coordinateCookieMutation(async () => "server-owned")).resolves.toBe("server-owned");
  });
});
