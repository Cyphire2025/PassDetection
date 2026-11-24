import { afterEach, beforeEach, expect, it, vi } from "vitest";
import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { capturePrivateOperationOwner } from "./request-owner";
import apiClient from "./client";

const actor: User = { id: "actor-a", email: "a@example.test", full_name: "Synthetic A", role: "agency_admin", agency_id: "agency-a",
  is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
beforeEach(() => useAuthStore.setState({ user: actor, sessionVersion: 1 }));
afterEach(() => vi.restoreAllMocks());

it.each([{ role: "agency_staff" as const }, { agency_id: "agency-b" }])("rejects an old private operation after same-user authority changes: %j", (changed) => {
  const operation = capturePrivateOperationOwner();
  useAuthStore.setState({ user: { ...actor, ...changed } });
  expect(() => operation.assertCurrent()).toThrowError(expect.objectContaining({ code: "AUTH_REQUEST_OWNER_CHANGED" }));
  expect(operation.requestConfig).toEqual({ expectedOwnerUserId: actor.id,
    expectedAuthorityKey: JSON.stringify([actor.id, actor.role, actor.agency_id]) });
});

it("preserves same-authority operations across sessionVersion/profile revalidation", () => {
  const operation = capturePrivateOperationOwner();
  useAuthStore.setState({ user: { ...actor, last_login_at: "2026-10-31", updated_at: "2026-10-31" }, sessionVersion: 2 });
  expect(() => operation.assertCurrent()).not.toThrow();
});

it.each([{ role: "agency_staff" as const }, { agency_id: "agency-b" }])("aborts and suppresses an old ordinary private response after same-user authority changes: %j", async (changed) => {
  let release!: () => void;
  let request!: InternalAxiosRequestConfig;
  const pending = apiClient.post("/api/v1/private-mutation", { reviewed: "A private payload" }, {
    adapter: async (config) => {
      request = config;
      await new Promise<void>((resolve) => { release = resolve; });
      return { config, status: 200, statusText: "OK", headers: new AxiosHeaders(), data: { private: "A result" } };
    },
  }).then((result) => ({ result }), (error: unknown) => ({ error }));
  expect(() => useAuthStore.setState({ user: { ...actor, ...changed }, sessionVersion: 2 })).not.toThrow();
  const aborted = request.signal?.aborted;
  release();
  const result = await pending;
  expect(aborted).toBe(true);
  expect(result).toMatchObject({ error: { code: "AUTH_REQUEST_OWNER_CHANGED" } });
  expect(JSON.parse(request.data)).toEqual({ reviewed: "A private payload" });
  expect(request.headers.get("X-Expected-Actor-Id")).toBe(actor.id);
});

it("permits an ordinary private response through same-authority session/profile renewal", async () => {
  let release!: () => void;
  let request!: InternalAxiosRequestConfig;
  const pending = apiClient.get("/api/v1/private-data", { adapter: async (config) => {
    request = config; await new Promise<void>((resolve) => { release = resolve; });
    return { config, status: 200, statusText: "OK", headers: new AxiosHeaders(), data: "same authority" };
  } });
  useAuthStore.setState({ user: { ...actor, updated_at: "2026-10-31" }, sessionVersion: 2 });
  expect(request.signal?.aborted).toBe(false);
  release();
  await expect(pending).resolves.toHaveProperty("data", "same authority");
});

it("does not replay a private mutation into a new effective agency after refresh awaits", async () => {
  let release!: () => void;
  const started = new Promise<void>((resolve) => {
    vi.spyOn(axios, "post").mockImplementation(async () => {
      resolve(); await new Promise<void>((finish) => { release = finish; });
      return { data: { status: "authenticated", user: actor } };
    });
  });
  let attempts = 0;
  const pending = apiClient.post("/api/v1/private-mutation", {}, { adapter: async (config) => {
    attempts += 1;
    if (attempts === 1) throw new AxiosError("Refresh needed", "ERR_BAD_RESPONSE", config, undefined, {
      config, status: 401, statusText: "Unauthorized", headers: new AxiosHeaders(), data: {},
    });
    return { config, status: 200, statusText: "OK", headers: new AxiosHeaders(), data: "new agency result" };
  } }).then((result) => ({ result }), (error: unknown) => ({ error }));
  await started;
  useAuthStore.setState({ user: { ...actor, agency_id: "agency-b" }, sessionVersion: 2 });
  release();
  expect(await pending).toMatchObject({ error: { code: "AUTH_REQUEST_OWNER_CHANGED" } });
  expect(attempts).toBe(1);
});
