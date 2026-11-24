import axios, { AxiosError, AxiosHeaders, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installBrowserLocks } from "@/test-support/browser-locks";

const authentication = vi.hoisted(() => {
  const state = { user: { id: "owner-a" } as { id: string } | null, clearSession: vi.fn() };
  const listeners = new Set<(value: typeof state) => void>();
  return {
    state,
    listeners,
    refresh: vi.fn(),
    stepUp: vi.fn(),
    changeOwner(id: string | null) {
      state.user = id === null ? null : { id };
      listeners.forEach((listener) => listener(state));
    },
  };
});

vi.mock("@/stores/auth.store", () => ({
  useAuthStore: {
    getState: () => authentication.state,
    subscribe: (listener: (state: typeof authentication.state) => void) => {
      authentication.listeners.add(listener);
      return () => authentication.listeners.delete(listener);
    },
  },
}));
vi.mock("@/features/auth/services/refresh-coordinator", () => ({
  readRefreshEpoch: () => "synthetic-epoch",
  runCoordinatedRefresh: authentication.refresh,
}));
vi.mock("@/features/auth/services/step-up-coordinator", () => ({
  requestAuthenticationStepUp: authentication.stepUp,
}));

import apiClient from "./client";
import { capturePrivateOperationOwner, ownerBoundAdapter, ownerBoundRequestConfig } from "./request-owner";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function response(config: InternalAxiosRequestConfig) {
  return { data: { private: "owner-a-only" }, status: 200, statusText: "OK", headers: new AxiosHeaders(), config };
}

function failure(config: InternalAxiosRequestConfig, status: number) {
  return new AxiosError("Authentication required", "ERR_BAD_RESPONSE", config, undefined, {
    ...response(config), status,
    data: { error: { code: status === 403 ? "STEP_UP_REQUIRED" : "AUTH_EXPIRED", message: "Authenticate again" } },
  });
}

describe("owner-bound private requests", () => {
  let locks: ReturnType<typeof installBrowserLocks>;
  beforeEach(() => {
    locks = installBrowserLocks();
    authentication.changeOwner("owner-a");
    authentication.refresh.mockReset().mockResolvedValue(undefined);
    authentication.stepUp.mockReset().mockResolvedValue(undefined);
    authentication.state.clearSession.mockReset();
    expect(authentication.listeners.size).toBe(0);
  });
  afterEach(() => locks.restore());

  it("keeps a chained operation bound to its initiating actor", () => {
    const operation = capturePrivateOperationOwner();
    expect(operation.requestConfig).toEqual({ expectedOwnerUserId: "owner-a", expectedAuthorityKey: '["owner-a",null,null]' });
    expect(() => operation.assertCurrent()).not.toThrow();
    authentication.changeOwner("owner-b");
    expect(() => operation.assertCurrent()).toThrowError(expect.objectContaining({ code: "AUTH_REQUEST_OWNER_CHANGED" }));
    expect(operation.requestConfig).toEqual({ expectedOwnerUserId: "owner-a", expectedAuthorityKey: '["owner-a",null,null]' });
  });

  it("cannot start a private chain without a known actor and later inherit another actor", () => {
    authentication.changeOwner(null);
    expect(() => capturePrivateOperationOwner()).toThrowError(expect.objectContaining({ code: "AUTH_REQUEST_OWNER_CHANGED" }));
  });

  it("rejects a known owner mismatch before any transport dispatch", async () => {
    const adapter = vi.fn<AxiosAdapter>();
    authentication.changeOwner("owner-b");
    await expect(apiClient.post("/api/v1/private", { scan: "private-qr" }, {
      ...ownerBoundRequestConfig("owner-a"), adapter,
    })).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(adapter).not.toHaveBeenCalled();
  });

  it("checks again after asynchronous request interceptors immediately before dispatch", async () => {
    const waiting = deferred<void>();
    const entered = deferred<void>();
    const interceptor = apiClient.interceptors.request.use(async (config) => {
      entered.resolve();
      await waiting.promise;
      return config;
    });
    const adapter = vi.fn<AxiosAdapter>();
    const request = apiClient.post("/api/v1/private", { scan: "private-qr" }, {
      ...ownerBoundRequestConfig("owner-a"), adapter,
    });
    const rejected = expect(request).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    try {
      await entered.promise;
      authentication.changeOwner("owner-b");
      waiting.resolve();
      await rejected;
      expect(adapter).not.toHaveBeenCalled();
    } finally { apiClient.interceptors.request.eject(interceptor); }
  });

  it.each([true, false])("aborts in-flight delivery and suppresses stale output (explicit owner: %s)", async (explicitOwner) => {
    const entered = deferred<InternalAxiosRequestConfig>();
    const waiting = deferred<void>();
    const adapter: AxiosAdapter = async (config) => {
      entered.resolve(config);
      await waiting.promise;
      return response(config);
    };
    const request = apiClient.get("/api/v1/private", { ...(explicitOwner ? ownerBoundRequestConfig("owner-a") : {}), adapter });
    const rejected = expect(request).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    const dispatched = await entered.promise;
    expect(dispatched.headers.get("X-Expected-Actor-Id")).toBe("owner-a");
    expect(dispatched.signal?.aborted).toBe(false);
    authentication.changeOwner("owner-b");
    expect(dispatched.signal?.aborted).toBe(true);
    waiting.resolve();
    await rejected;
    expect(authentication.listeners.size).toBe(0);
  });

  it("guards the final adapter even when a later interceptor runs after owner binding", async () => {
    const client = axios.create();
    const transport = vi.fn<AxiosAdapter>();
    // Axios request interceptors execute in reverse registration order. This
    // simulates asynchronous work added before the owner-binding interceptor.
    client.interceptors.request.use(async (config) => {
      await Promise.resolve();
      authentication.changeOwner("owner-b");
      return config;
    });
    client.interceptors.request.use((config) => {
      config.adapter = ownerBoundAdapter(transport);
      return config;
    });
    await expect(client.post("/api/v1/private", {}, ownerBoundRequestConfig("owner-a")))
      .rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(transport).not.toHaveBeenCalled();
  });

  it.each([401, 403])("does not replay the original body after an owner switch during authentication status %s", async (status) => {
    const entered = deferred<void>();
    const waiting = deferred<void>();
    const authenticate = status === 401 ? authentication.refresh : authentication.stepUp;
    authenticate.mockImplementation(async () => { entered.resolve(); await waiting.promise; });
    const adapter = vi.fn<AxiosAdapter>().mockImplementation(async (config) => { throw failure(config, status); });
    const request = apiClient.post("/api/v1/private", { scan: "owner-a-qr" }, {
      ...ownerBoundRequestConfig("owner-a"), adapter,
    });
    const rejected = expect(request).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await entered.promise;
    authentication.changeOwner("owner-b");
    waiting.resolve();
    await rejected;
    expect(adapter).toHaveBeenCalledTimes(1);
    expect(authentication.listeners.size).toBe(0);
  });

  it.each([401, 403])("automatically binds an ordinary private mutation across authentication status %s", async (status) => {
    const entered = deferred<void>();
    const waiting = deferred<void>();
    const authenticate = status === 401 ? authentication.refresh : authentication.stepUp;
    authenticate.mockImplementation(async () => { entered.resolve(); await waiting.promise; });
    let attempts = 0;
    const adapter: AxiosAdapter = async (config) => {
      if (++attempts === 1) throw failure(config, status);
      return response(config);
    };
    const request = apiClient.post("/api/v1/companies/company-a", { private: "owner-a-command" }, { adapter });
    const rejected = expect(request).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await entered.promise;
    authentication.changeOwner("owner-b");
    waiting.resolve();
    await rejected;
    expect(attempts).toBe(1);
    expect(authentication.state.clearSession).not.toHaveBeenCalled();
  });

  it("does not clear the new account when the previous account's refresh fails", async () => {
    const entered = deferred<void>();
    const waiting = deferred<void>();
    authentication.refresh.mockImplementation(async () => {
      entered.resolve();
      await waiting.promise;
      throw new AxiosError("Old refresh denied", "ERR_BAD_RESPONSE", undefined, undefined, {
        status: 401, statusText: "Unauthorized", data: {}, headers: new AxiosHeaders(), config: {} as InternalAxiosRequestConfig,
      });
    });
    const adapter: AxiosAdapter = async (config) => { throw failure(config, 401); };
    const request = apiClient.delete("/api/v1/companies/company-a", { adapter });
    const rejected = expect(request).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await entered.promise;
    authentication.changeOwner("owner-b");
    waiting.resolve();
    await rejected;
    expect(authentication.state.clearSession).not.toHaveBeenCalled();
    expect(authentication.state.user?.id).toBe("owner-b");
  });

  it("preserves the expected actor and original caller cancellation across a legitimate refresh retry", async () => {
    const controller = new AbortController();
    const attempts: AbortSignal[] = [];
    const adapter = vi.fn<AxiosAdapter>().mockImplementation(async (config) => {
      expect(config.headers.get("X-Expected-Actor-Id")).toBe("owner-a");
      attempts.push(config.signal as AbortSignal);
      if (attempts.length === 1) throw failure(config, 401);
      controller.abort();
      expect(config.signal?.aborted).toBe(true);
      return response(config);
    });
    await expect(apiClient.post("/api/v1/private", {}, {
      ...ownerBoundRequestConfig("owner-a"), adapter, signal: controller.signal,
    })).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    expect(adapter).toHaveBeenCalledTimes(2);
    expect(attempts[0]).not.toBe(controller.signal);
    expect(attempts[1]).not.toBe(controller.signal);
    expect(authentication.refresh).toHaveBeenCalledTimes(1);
    expect(authentication.listeners.size).toBe(0);
  });

  it.each([401, 403])("retries for the same owner after status %s and returns the private response", async (status) => {
    let attempt = 0;
    const adapter: AxiosAdapter = async (config) => {
      expect(config.headers.get("X-Expected-Actor-Id")).toBe("owner-a");
      if (++attempt === 1) throw failure(config, status);
      return response(config);
    };
    const result = await apiClient.post("/api/v1/private", {}, { adapter });
    expect(result.data).toEqual({ private: "owner-a-only" });
    expect(attempt).toBe(2);
    expect(authentication.listeners.size).toBe(0);
  });

  it("still expires a rejected refresh for the unchanged owner", async () => {
    authentication.refresh.mockRejectedValue(new AxiosError("Refresh denied", "ERR_BAD_RESPONSE", undefined, undefined, {
      status: 401, statusText: "Unauthorized", data: {}, headers: new AxiosHeaders(), config: {} as InternalAxiosRequestConfig,
    }));
    const adapter: AxiosAdapter = async (config) => { throw failure(config, 401); };
    await expect(apiClient.get("/api/v1/companies", { adapter })).rejects.toMatchObject({ code: "AUTH_SESSION_EXPIRED" });
    expect(authentication.state.clearSession).toHaveBeenCalledExactlyOnceWith("session_expired", { revokeServerSession: false });
  });

  it("leaves ordinary and public request headers and caller signals unchanged", async () => {
    const controller = new AbortController();
    authentication.changeOwner(null);
    const adapter: AxiosAdapter = async (config) => {
      expect(config.headers.has("X-Expected-Actor-Id")).toBe(false);
      expect(config.signal).toBe(controller.signal);
      expect(authentication.listeners.size).toBe(0);
      return response(config);
    };
    await expect(apiClient.get("/api/v1/public-drafts/synthetic", { signal: controller.signal, adapter })).resolves.toMatchObject({ status: 200 });
  });

  it.each([
    "/api/v1/auth/me", "/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout",
    "/api/v1/auth/activate", "/api/v1/auth/mfa/verify", "/api/v1/auth/password/recovery/complete",
    "/api/v1/returning/claims", "/api/v1/public-drafts/group-a/complete",
    "/api/v1/passports/upload/token-a/submission-a/status", "/api/v1/upload-links/token/token-a/qualifier-selection",
    "/api/v1/passports/submission-a/client-submit", "/api/v1/passports/submission-a/contact-otp/verify",
    "/api/v1/health/live", "/oauth/mcp/requests/request-a",
  ])("keeps identity bootstrap and public proof requests independent of the staff owner: %s", async (url) => {
    const controller = new AbortController();
    const adapter: AxiosAdapter = async (config) => {
      expect(config.headers.has("X-Expected-Actor-Id")).toBe(false);
      expect(config.signal).toBe(controller.signal);
      expect(authentication.listeners.size).toBe(0);
      authentication.changeOwner("owner-b");
      return response(config);
    };
    await expect(apiClient.request({ url, method: "post", data: {}, adapter, signal: controller.signal }))
      .resolves.toMatchObject({ status: 200 });
  });

  it.each([
    "/api/v1/auth/access-level", "/api/v1/auth/password/change",
    "/api/v1/auth/mfa/step-up", "/api/v1/auth/mfa/recovery-codes/regenerate",
  ])("binds authenticated identity commands to the known staff actor: %s", async (url) => {
    const adapter: AxiosAdapter = async (config) => {
      expect(config.headers.get("X-Expected-Actor-Id")).toBe("owner-a");
      return response(config);
    };
    await apiClient.post(url, {}, { adapter });
  });
});
