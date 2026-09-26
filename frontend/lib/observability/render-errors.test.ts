import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal("crypto", webcrypto);
  window.history.replaceState({}, "", "/upload/private-token?email=secret%40example.test#private");
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.useRealTimers(); window.history.replaceState({}, "", "/"); });

const acceptedFetch = () => vi.fn(async (_url: string, options: RequestInit) => ({
  status: 202, json: async () => ({ event_id: JSON.parse(String(options.body)).event_id }),
}));

describe("privacy-safe render error reporting", () => {
  it("sends metadata only, associates build and support ID, and deduplicates StrictMode/repeated faults", async () => {
    vi.stubEnv("NEXT_PUBLIC_APP_REVISION", "6033b9f3");
    const fetch = acceptedFetch(); vi.stubGlobal("fetch", fetch);
    const { reportRenderError } = await import("./render-errors");
    const error = new TypeError("Passport A1234567; bearer secret; secret@example.test");
    error.stack = "secret document contents and contact details";
    const first = reportRenderError(error, "shared");
    expect(reportRenderError(error, "shared")).toBe(first);
    const reference = await first;
    expect(reference).toMatch(/^[a-f0-9-]{36}$/);
    expect(fetch).toHaveBeenCalledOnce();
    const [url, options] = fetch.mock.calls[0];
    const body = JSON.parse(String(options.body));
    expect(url).toBe("/api/v1/observability/frontend-errors");
    expect(body).toEqual({ event_id: reference, fingerprint: expect.stringMatching(/^[a-f0-9]{32}$/), release: "6033b9f3", route: "/upload/[token]", boundary: "shared", error_kind: "TypeError" });
    expect(options).toMatchObject({ credentials: "omit", referrerPolicy: "no-referrer", cache: "no-store" });
    expect(options.body).not.toMatch(/private|Passport|bearer|example|document contents/);
  });
  it("bounds per-page collection and never collects unknown raw paths", async () => {
    const fetch = acceptedFetch(); vi.stubGlobal("fetch", fetch);
    const { reportRenderError } = await import("./render-errors");
    const paths = ["/dashboard", "/passports", "/menu", "/settings", "/documents", "/gc-app", "/whatsapp", "/rooming", "/analytics", "/admin", "/staff"];
    for (const path of paths) { window.history.replaceState({}, "", path); await reportRenderError(new Error("private"), "route"); }
    expect(fetch).toHaveBeenCalledTimes(10);
    expect(await reportRenderError(new RangeError("private"), "global")).toBeNull();
  });
  it("uses the actual retained support receipt when the collector deduplicates across tabs", async () => {
    const retained = "56dce0c7-74c7-4c93-adab-f1bd8298a15a";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 202, json: async () => ({ event_id: retained }) }));
    const { reportRenderError } = await import("./render-errors");
    expect(await reportRenderError(new Error("private"), "shared")).toBe(retained);
  });
  it.each([null, {}, { event_id: "untrusted non-reference" }])("does not display a malformed collector receipt", async (receipt) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 202, json: async () => receipt }));
    const { reportRenderError } = await import("./render-errors");
    expect(await reportRenderError(new Error("private"), "shared")).toBeNull();
  });
  it.each([503, 429, 403])("does not claim a support receipt or retry a rejected %i report", async (status) => {
    const fetch = vi.fn().mockResolvedValue({ status }); vi.stubGlobal("fetch", fetch);
    const { reportRenderError } = await import("./render-errors");
    expect(await reportRenderError(new Error("private"), "route")).toBeNull();
    expect(await reportRenderError(new Error("private"), "route")).toBeNull();
    expect(fetch).toHaveBeenCalledOnce();
  });
  it("degrades safely without browser crypto or collector connectivity", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("offline")); vi.stubGlobal("fetch", fetch);
    const { reportRenderError } = await import("./render-errors");
    expect(await reportRenderError(new Error("private"), "route")).toBeNull();
    vi.stubGlobal("crypto", {});
    expect(await reportRenderError(new Error("private"), "global")).toBeNull();
    expect(fetch).toHaveBeenCalledOnce();
  });
});
