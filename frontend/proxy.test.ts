import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import {
  PROTECTED_PREFIXES,
  buildContentSecurityPolicy,
  proxy,
} from "./proxy";

describe("dashboard proxy boundary", () => {
  it.each(PROTECTED_PREFIXES)("redirects unauthenticated requests for %s", (prefix) => {
    const response = proxy(new NextRequest(`https://dashboard.example${prefix}`));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain(`/login?from=${encodeURIComponent(prefix)}`);
  });

  it("matches complete route segments rather than lookalike public paths", () => {
    const response = proxy(new NextRequest("https://dashboard.example/documents-public"));
    expect(response.status).toBe(200);
  });

  it("keeps an authenticated request and attaches a request-specific CSP", () => {
    const request = new NextRequest("https://dashboard.example/documents", {
      headers: { cookie: "access_token=test-session" },
    });
    const response = proxy(request);
    expect(response.status).toBe(200);
    expect(response.headers.get("content-security-policy")).toContain("'nonce-");
  });

  it("redirects an authenticated login request to a validated in-app destination", () => {
    const request = new NextRequest("https://dashboard.example/login?from=%2Fdocuments", {
      headers: { cookie: "access_token=test-session" },
    });
    const response = proxy(request);
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("https://dashboard.example/documents");
  });
});

describe("production CSP", () => {
  it("does not permit arbitrary inline or eval-based scripts", () => {
    const policy = buildContentSecurityPolicy("fixed-nonce", false);
    const scriptDirective = policy.split("; ").find((directive) => directive.startsWith("script-src "));
    expect(scriptDirective).toContain("'nonce-fixed-nonce'");
    expect(scriptDirective).toContain("'strict-dynamic'");
    expect(scriptDirective).toContain("'wasm-unsafe-eval'");
    expect(scriptDirective).not.toContain("'unsafe-inline'");
    expect(scriptDirective).not.toMatch(/(?:^| )'unsafe-eval'(?: |$)/);
    expect(policy).toContain("script-src-attr 'none'");
  });
});
