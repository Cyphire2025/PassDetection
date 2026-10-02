import { NextRequest } from "next/server";
import { describe,expect,it } from "vitest";
import {
PROTECTED_PREFIXES,
buildContentSecurityPolicy,
proxy,
} from "./proxy";

describe("dashboard proxy boundary", () => {
  it.each(PROTECTED_PREFIXES)("redirects unauthenticated requests for %s", (prefix) => {
    const response = proxy(new NextRequest(`https://dashboard.example${prefix}`));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain(`/session-restore?from=${encodeURIComponent(prefix)}`);
  });

  it("matches complete route segments rather than lookalike public paths", () => {
    const response = proxy(new NextRequest("https://dashboard.example/documents-public"));
    expect(response.status).toBe(200);
  });

  it("keeps the anonymous MCP waiting page outside the dashboard login boundary", () => {
    const response = proxy(new NextRequest("https://dashboard.example/mcp/connect?request_id=eaf5b697-d6ca-4a86-bf09-3b9780139fb1"));
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
  });

  it("redirects the legacy waiting URL publicly while dropping old OAuth query parameters", () => {
    const response = proxy(new NextRequest("https://dashboard.example/admin/mcp/connect?request_id=eaf5b697-d6ca-4a86-bf09-3b9780139fb1&state=private-state&redirect_uri=http://127.0.0.1:5555/callback"));
    const target = new URL(response.headers.get("location")!);
    expect(target.pathname).toBe("/mcp/connect");
    expect([...target.searchParams.keys()]).toEqual(["request_id"]);
  });

  it("keeps an authenticated request and attaches a request-specific CSP", () => {
    const request = new NextRequest("https://dashboard.example/documents", {
      headers: { cookie: "access_token=test-session" },
    });
    const response = proxy(request);
    expect(response.status).toBe(200);
    expect(response.headers.get("content-security-policy")).toContain("'nonce-");
  });

  it("keeps login available when an unverified stale cookie remains after rejected refresh", () => {
    const request = new NextRequest("https://dashboard.example/login?from=%2Fdocuments", {
      headers: { cookie: "access_token=test-session" },
    });
    const response = proxy(request);
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
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
