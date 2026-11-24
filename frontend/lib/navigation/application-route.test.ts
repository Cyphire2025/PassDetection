import { describe, expect, it } from "vitest";
import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import templates from "@/lib/observability/route-templates.json";
import { ROUTES } from "@/constants/routes";
import { applicationRouteTemplate, parseApplicationRoute } from "./application-route";

describe("validated route boundary", () => {
  it.each(["javascript:alert(1)", "//evil.test/dashboard", "/\\evil.test", "/missing-page", "/dashboard\n", "/coordinator/groups/"])("rejects unrecognized or unsafe %s", (value) => {
    expect(parseApplicationRoute(value)).toBeNull();
  });
  it("retains valid navigation context and encodes dynamic segment delimiters", () => {
    expect(parseApplicationRoute("/passports/groups/example?view=docs#row")).toBe("/passports/groups/example?view=docs#row");
    expect(ROUTES.dashboard.passportDetail("id/with?#delimiters")).toBe("/passports/id%2Fwith%3F%23delimiters");
  });
  it("never returns dynamic identifiers in the privacy template", () => {
    expect(applicationRouteTemplate("/upload/secret-token")).toBe("/upload/[token]");
    expect(applicationRouteTemplate("/passports/groups/private-id")).toBe("/passports/groups/[groupId]");
    expect(applicationRouteTemplate("/passports/unknownprivatevalue")).toBe("/passports/[id]");
    expect(applicationRouteTemplate("/passports/unknown/privatevalue")).toBe("unknown");
    expect(applicationRouteTemplate("/passports")).toBe("/passports");
  });
  it("keeps the checked-in privacy allowlist aligned with actual page files", () => {
    function pages(directory: string, segments: string[] = []): string[] {
      return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        if (entry.isDirectory()) {
          // Slots and route groups are filesystem organization. Same-level
          // intercepts resolve to the canonical destination's URL.
          const segment = entry.name.replace(/^\(\.\)/, "");
          const next = entry.name.startsWith("@") || /^\([^)]*\)$/.test(segment)
            ? segments : [...segments, segment];
          return pages(resolve(directory, entry.name), next);
        }
        return entry.name === "page.tsx" ? ["/" + segments.join("/")] : [];
      });
    }
    expect([...templates].sort()).toEqual([...new Set([...pages(resolve("app")), "unknown"])].sort());
  });
});
