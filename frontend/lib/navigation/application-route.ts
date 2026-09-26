import type { Route } from "next";
import templates from "@/lib/observability/route-templates.json";

// Static pages take precedence over a dynamic segment at the same depth.
const knownTemplates = templates.filter((route) => route !== "unknown")
  .sort((a, b) => (a.match(/\[/g)?.length ?? 0) - (b.match(/\[/g)?.length ?? 0));

export function applicationRouteTemplate(pathname: string): string {
  const parts = pathname.split("/");
  return knownTemplates.find((template) => {
    const expected = template.split("/");
    return expected.length === parts.length && expected.every((part, index) => (
      part.startsWith("[") ? Boolean(parts[index]) : part === parts[index]
    ));
  }) ?? "unknown";
}

/** The only dynamic route assertion: validate external/stored inputs first. */
export function parseApplicationRoute(value: string): Route | null {
  if (!value.startsWith("/") || value.startsWith("//") || /[\\\x00-\x20]/.test(value)) return null;
  const url = new URL(value, "https://workspace.invalid");
  if (url.origin !== "https://workspace.invalid" || applicationRouteTemplate(url.pathname) === "unknown") return null;
  return `${url.pathname}${url.search}${url.hash}` as Route;
}
