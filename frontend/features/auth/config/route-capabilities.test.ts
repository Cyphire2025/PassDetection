
import { describe, expect, it } from "vitest";
import { ROUTES } from "@/constants/routes";
import type { User, UserRole } from "@/types";
import {
  canAccessApplicationPath,
  firstAuthorizedPath,
  resolveRouteCapability,
} from "./route-capabilities";

function user(
  role: UserRole,
  overrides: Partial<User> = {},
): User {
  return {
    id: `${role}-id`,
    email: `${role}@example.test`,
    full_name: role,
    role,
    agency_id: role === "super_admin" ? null : "agency-1",
    is_active: true,
    last_login_at: null,
    created_at: "2026-08-23T00:00:00Z",
    updated_at: "2026-08-23T00:00:00Z",
    ...overrides,
  };
}

describe("typed route capability map", () => {
  it("uses the most-specific policy for coordinator administration deep links", () => {
    const deepLink = `${ROUTES.dashboard.tourOperationsCoordinators}/new`;

    expect(resolveRouteCapability(deepLink)).toBe("tour_operations.coordinators.manage");
    expect(canAccessApplicationPath(user("agency_manager"), deepLink)).toBe(true);
    expect(canAccessApplicationPath(user("agency_staff"), deepLink)).toBe(false);
    expect(canAccessApplicationPath(
      user("agency_staff"),
      ROUTES.dashboard.tourOperationsGroupAssignments,
    )).toBe(true);
  });

  it("fails closed for unregistered and near-prefix routes", () => {
    expect(resolveRouteCapability("/new-feature-being-built-elsewhere")).toBeNull();
    expect(canAccessApplicationPath(user("super_admin"), "/new-feature-being-built-elsewhere"))
      .toBe(false);
    expect(canAccessApplicationPath(user("super_admin"), "/passports-impersonation"))
      .toBe(false);
  });

  it("keeps audit and tenant administration boundaries role-specific", () => {
    expect(canAccessApplicationPath(user("super_admin"), ROUTES.dashboard.auditLogs)).toBe(true);
    expect(canAccessApplicationPath(user("agency_admin"), ROUTES.dashboard.auditLogs)).toBe(true);
    expect(canAccessApplicationPath(user("agency_manager"), ROUTES.dashboard.auditLogs)).toBe(false);
    expect(canAccessApplicationPath(user("agency_staff"), ROUTES.dashboard.admin)).toBe(false);
    expect(canAccessApplicationPath(user("agency_staff"), ROUTES.dashboard.root)).toBe(false);
    expect(canAccessApplicationPath(user("agency_coordinator"), ROUTES.dashboard.root)).toBe(false);
  });

  it("applies WhatsApp capability to the nested group tracking workflow", () => {
    const trackingPath = ROUTES.dashboard.passportGroupWhatsAppTracking("group-1");
    expect(resolveRouteCapability(trackingPath)).toBe("whatsapp.broadcast.manage");
    expect(canAccessApplicationPath(user("agency_manager"), trackingPath)).toBe(true);
    expect(canAccessApplicationPath(user("agency_staff"), trackingPath)).toBe(false);
  });

  it("denies inactive and missing sessions before a route can mount", () => {
    expect(canAccessApplicationPath(null, ROUTES.dashboard.root)).toBe(false);
    expect(canAccessApplicationPath(
      user("agency_admin", { is_active: false }),
      ROUTES.dashboard.root,
    )).toBe(false);
  });

  it("treats server-provided GC capabilities as authoritative during rollout", () => {
    expect(canAccessApplicationPath(user("agency_admin"), ROUTES.dashboard.gcAppRoot)).toBe(true);
    expect(canAccessApplicationPath(
      user("agency_admin", { capabilities: [] }),
      ROUTES.dashboard.gcAppRoot,
    )).toBe(false);
    expect(canAccessApplicationPath(
      user("agency_manager", { capabilities: ["gc_app.manage"] }),
      ROUTES.dashboard.gcAppRoot,
    )).toBe(true);
  });

  it("returns a role-safe landing page after a stale direct link is rejected", () => {
    expect(firstAuthorizedPath(user("agency_coordinator"))).toBe(ROUTES.coordinator);
    expect(firstAuthorizedPath(user("agency_staff"))).toBe(ROUTES.dashboard.passports);
  });
});
