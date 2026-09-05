/**
 * Next.js Proxy — Optimistic Route Protection
 * ===========================================
 * Runs at the request boundary before a page renders. Cookie presence avoids
 * mounting obviously unauthenticated pages; API authorization remains the
 * authoritative security boundary and the client capability map fails closed
 * while the signed-in user record is loading.
 *
 * Protected routes: dashboard and office feature routes, including email integrations
 * Public routes:    /login, /upload/[token]
 */

import { type NextRequest, NextResponse } from "next/server";

export const PROTECTED_PREFIXES = [
  "/coordinator",
  "/tour-scanner",
  "/dashboard",
  "/passports",
  "/upload-links",
  "/whatsapp",
  "/email-integrations",
  "/documents",
  "/tour-operations",
  "/rooming",
  "/menu",
  "/gc-app",
  "/admin",
  "/staff",
  "/analytics",
  "/audit-logs",
  "/old-data",
  "/notifications",
  "/settings",
];

function matchesRouteBoundary(pathname: string, prefix: string) {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function buildContentSecurityPolicy(nonce: string, isDevelopment: boolean) {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' 'wasm-unsafe-eval'${
      isDevelopment ? " 'unsafe-eval'" : ""
    }`,
    "script-src-attr 'none'",
    isDevelopment
      ? "style-src 'self' 'unsafe-inline'"
      : `style-src 'self' 'nonce-${nonce}'`,
    // React uses style attributes for bounded dynamic layout values such as
    // crop overlays and progress widths. Keep that capability isolated from
    // executable scripts and arbitrary inline style elements.
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
  ].join("; ");
}

function withContentSecurityPolicy(response: NextResponse, value: string) {
  response.headers.set("Content-Security-Policy", value);
  return response;
}

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const contentSecurityPolicy = buildContentSecurityPolicy(
    nonce,
    process.env.NODE_ENV === "development",
  );

  // The backend sets this HttpOnly cookie. Presence is only an optimistic
  // navigation hint; proxy code cannot validate the full account authority.
  const accessToken = request.cookies.get("access_token")?.value;
  const isAuthenticated = Boolean(accessToken);

  const isProtected = PROTECTED_PREFIXES.some((prefix) =>
    matchesRouteBoundary(pathname, prefix)
  );

  // Redirect unauthenticated users away from protected pages
  if (isProtected && !isAuthenticated) {
    const loginUrl = new URL("/session-restore", request.url);
    loginUrl.searchParams.set("from", `${pathname}${request.nextUrl.search}`);
    return withContentSecurityPolicy(NextResponse.redirect(loginUrl), contentSecurityPolicy);
  }

  // Cookie presence cannot prove an authenticated account. Leave sign-in
  // accessible after a rejected refresh even if a stale access cookie remains.

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", contentSecurityPolicy);
  return withContentSecurityPolicy(
    NextResponse.next({ request: { headers: requestHeaders } }),
    contentSecurityPolicy,
  );
}

export const config = {
  // Run middleware on all routes except static files and Next.js internals
  matcher: [
    "/((?!api|_next/|favicon.ico|public/).*)",
  ],
};
