import { describe, expect, it } from "vitest";
import {
  resolveApiRewriteBase,
  resolveServerApiBaseUrl,
  validateApiOrigin,
} from "./api-routing";

describe("API routing policy", () => {
  it("keeps production same-origin when only a public build-time value exists", () => {
    expect(resolveApiRewriteBase({
      NODE_ENV: "production",
      NEXT_PUBLIC_API_BASE_URL: "https://stale.example.test",
    })).toBeNull();
    expect(resolveServerApiBaseUrl({
      NODE_ENV: "production",
      NEXT_PUBLIC_API_BASE_URL: "https://stale.example.test",
    })).toBe("");
  });

  it("uses the server-only production origin and strips its trailing slash", () => {
    expect(resolveApiRewriteBase({
      NODE_ENV: "production",
      API_BASE_URL: "http://backend:8000/",
    })).toBe("http://backend:8000");
  });

  it("supports the legacy public override only during development", () => {
    expect(resolveApiRewriteBase({
      NODE_ENV: "development",
      NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:9000",
    })).toBe("http://127.0.0.1:9000");
    expect(resolveApiRewriteBase({ NODE_ENV: "development" })).toBe("http://localhost:8000");
  });

  it("fails closed on non-origin and credential-bearing values", () => {
    expect(() => validateApiOrigin("javascript:alert(1)")).toThrow();
    expect(() => validateApiOrigin("https://user:secret@example.test")).toThrow();
    expect(() => validateApiOrigin("https://example.test/api")).toThrow();
    expect(() => validateApiOrigin("https://example.test?tenant=one")).toThrow();
  });
});
