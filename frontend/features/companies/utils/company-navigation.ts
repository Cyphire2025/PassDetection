import type { Route } from "next";
import { ROUTES } from "@/constants/routes";

/** Company return locations are local and allowlisted; never follow arbitrary URLs. */
export function safeCompanyReturn(value: string | null): Route | null {
  if (!value || value.length > 8_192 || !value.startsWith("/companies/")) return null;
  try {
    const url = new URL(value, "https://company.invalid");
    if (url.origin !== "https://company.invalid" || value.split(/[?#]/)[0] !== url.pathname || !/^\/companies\/[a-zA-Z0-9-]+(?:\/people\/[a-zA-Z0-9-]+)?$/.test(url.pathname)) return null;
    return (url.pathname + url.search) as Route;
  } catch { return null; }
}

export function companyViewHref(companyId: string, query = ""): Route {
  return `/companies/${encodeURIComponent(companyId)}${query ? `?${query}` : ""}` as Route;
}

export function companyPersonHref(companyId: string, personId: string, query = ""): Route {
  return `/companies/${encodeURIComponent(companyId)}/people/${encodeURIComponent(personId)}${query ? `?${query}` : ""}` as Route;
}

export function companyGroupHref(groupId: string, returnTo: string): Route {
  const destination = safeCompanyReturn(returnTo);
  return `${ROUTES.dashboard.passportGroup(groupId)}${destination ? `?${new URLSearchParams({ returnTo: destination })}` : ""}` as Route;
}
