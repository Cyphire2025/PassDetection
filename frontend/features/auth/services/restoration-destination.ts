import type { Route } from "next";

/** A return URL must remain in the workspace and cannot re-enter restoration. */
export function safeRestorationDestination(value?: string): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\x00-\x20]/.test(value)) {
    return "/dashboard";
  }
  const parsed = new URL(value, "https://workspace.invalid");
  if (parsed.origin !== "https://workspace.invalid" || /^\/(?:login|session-restore)(?:\/|$)/.test(parsed.pathname)) {
    return "/dashboard";
  }
  return `${parsed.pathname}${parsed.search}`;
}

export function expiredSessionSignInPath(pathname: string, search: string): Route {
  const params = new URLSearchParams({ reason: "session_expired" });
  if (pathname !== "/" && pathname !== "/login") {
    const original = pathname === "/session-restore"
      ? new URLSearchParams(search).get("from") ?? undefined
      : `${pathname}${search}`;
    params.set("from", safeRestorationDestination(original));
  }
  return `/login?${params.toString()}` as Route;
}
