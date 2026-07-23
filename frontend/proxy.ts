/**
 * Next.js Middleware — Route Protection
 * ================================
 * Runs on the Edge before any page renders.
 * Redirects unauthenticated users away from protected routes.
 *
 * Protected routes: anything under /dashboard, /passports, /upload-links, /settings
 * Public routes:    /login, /upload/[token]
 */

import { type NextRequest, NextResponse } from "next/server";

const PROTECTED_PREFIXES = [
  "/coordinator",
  "/dashboard",
  "/passports",
  "/upload-links",
  "/settings",
];

const AUTH_ROUTES = ["/login"];

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  // Check for auth token cookie (set by the frontend after login)
  const accessToken = request.cookies.get("access_token")?.value;
  const isAuthenticated = Boolean(accessToken);

  const isProtected = PROTECTED_PREFIXES.some((prefix) =>
    pathname.startsWith(prefix)
  );
  const isAuthRoute = AUTH_ROUTES.some((route) => pathname.startsWith(route));

  // Redirect unauthenticated users away from protected pages
  if (isProtected && !isAuthenticated) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", `${pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(loginUrl);
  }

  // Redirect authenticated users away from auth pages
  if (isAuthRoute && isAuthenticated) {
    const requestedPath = request.nextUrl.searchParams.get("from");
    const destination = requestedPath
      && requestedPath.startsWith("/")
      && !requestedPath.startsWith("//")
      && !requestedPath.includes("\\")
      ? requestedPath
      : "/dashboard";
    return NextResponse.redirect(new URL(destination, request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Run middleware on all routes except static files and Next.js internals
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|public/).*)",
  ],
};
