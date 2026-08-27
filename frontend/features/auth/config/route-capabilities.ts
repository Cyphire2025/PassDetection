
import { ROUTES } from "@/constants/routes";
import { canManageGcApp } from "@/lib/utils/role-access";
import type { User, UserRole } from "@/types";

export type ApplicationCapability =
  | "dashboard.overview.view"
  | "passports.workspace.view"
  | "whatsapp.broadcast.manage"
  | "email.integrations.view"
  | "documents.workspace.view"
  | "tour_operations.view"
  | "tour_operations.coordinators.manage"
  | "rooming.workspace.view"
  | "menu.workspace.view"
  | "gc_app.manage"
  | "accounts.admin.manage"
  | "accounts.staff.manage"
  | "analytics.view"
  | "audit_ledger.view"
  | "settings.manage"
  | "legacy_data.manage"
  | "coordinator_app.use";

interface RouteCapabilityPolicy {
  prefix: string;
  capability: ApplicationCapability;
  exact?: boolean;
}

interface DynamicRouteCapabilityPolicy {
  pattern: RegExp;
  capability: ApplicationCapability;
}

const OFFICE_ROLES: readonly UserRole[] = [
  "super_admin",
  "agency_admin",
  "agency_manager",
  "agency_staff",
];

const ROLE_CAPABILITIES: Record<UserRole, readonly ApplicationCapability[]> = {
  super_admin: [
    "dashboard.overview.view",
    "passports.workspace.view",
    "whatsapp.broadcast.manage",
    "email.integrations.view",
    "documents.workspace.view",
    "tour_operations.view",
    "tour_operations.coordinators.manage",
    "rooming.workspace.view",
    "menu.workspace.view",
    "accounts.admin.manage",
    "accounts.staff.manage",
    "analytics.view",
    "audit_ledger.view",
    "settings.manage",
    "legacy_data.manage",
  ],
  agency_admin: [
    "dashboard.overview.view",
    "passports.workspace.view",
    "whatsapp.broadcast.manage",
    "email.integrations.view",
    "documents.workspace.view",
    "tour_operations.view",
    "tour_operations.coordinators.manage",
    "rooming.workspace.view",
    "menu.workspace.view",
    "accounts.admin.manage",
    "accounts.staff.manage",
    "analytics.view",
    "audit_ledger.view",
    "settings.manage",
  ],
  agency_manager: [
    "dashboard.overview.view",
    "passports.workspace.view",
    "whatsapp.broadcast.manage",
    "email.integrations.view",
    "documents.workspace.view",
    "tour_operations.view",
    "tour_operations.coordinators.manage",
    "rooming.workspace.view",
    "menu.workspace.view",
    "accounts.staff.manage",
  ],
  agency_staff: [
    "passports.workspace.view",
    "email.integrations.view",
    "documents.workspace.view",
    "tour_operations.view",
    "rooming.workspace.view",
    "menu.workspace.view",
  ],
  agency_coordinator: ["coordinator_app.use"],
};

// Most-specific prefixes must come first. An unmapped dashboard route is
// intentionally denied until its feature owner declares a capability here.
export const ROUTE_CAPABILITY_POLICIES: readonly RouteCapabilityPolicy[] = [
  {
    prefix: ROUTES.dashboard.tourOperationsCoordinators,
    capability: "tour_operations.coordinators.manage",
  },
  { prefix: ROUTES.dashboard.passports, capability: "passports.workspace.view" },
  { prefix: ROUTES.dashboard.uploadLinks, capability: "passports.workspace.view" },
  { prefix: ROUTES.dashboard.whatsapp, capability: "whatsapp.broadcast.manage" },
  { prefix: ROUTES.dashboard.emailIntegrations, capability: "email.integrations.view" },
  { prefix: ROUTES.dashboard.documents, capability: "documents.workspace.view" },
  { prefix: ROUTES.dashboard.tourOperations, capability: "tour_operations.view" },
  { prefix: ROUTES.dashboard.rooming, capability: "rooming.workspace.view" },
  { prefix: ROUTES.dashboard.menu, capability: "menu.workspace.view" },
  { prefix: ROUTES.dashboard.gcAppRoot, capability: "gc_app.manage" },
  { prefix: ROUTES.dashboard.admin, capability: "accounts.admin.manage" },
  { prefix: ROUTES.dashboard.staff, capability: "accounts.staff.manage" },
  { prefix: ROUTES.dashboard.analytics, capability: "analytics.view" },
  { prefix: ROUTES.dashboard.auditLogs, capability: "audit_ledger.view" },
  { prefix: ROUTES.dashboard.settings, capability: "settings.manage" },
  { prefix: ROUTES.dashboard.oldData, capability: "legacy_data.manage" },
  { prefix: ROUTES.dashboard.root, capability: "dashboard.overview.view", exact: true },
  { prefix: ROUTES.coordinator, capability: "coordinator_app.use" },
];

const DYNAMIC_ROUTE_CAPABILITY_POLICIES: readonly DynamicRouteCapabilityPolicy[] = [
  {
    pattern: /^\/passports\/groups\/[^/]+\/whatsapp(?:\/|$)/,
    capability: "whatsapp.broadcast.manage",
  },
];

export function resolveRouteCapability(pathname: string): ApplicationCapability | null {
  const dynamicCapability = DYNAMIC_ROUTE_CAPABILITY_POLICIES.find((policy) => (
    policy.pattern.test(pathname)
  ))?.capability;
  if (dynamicCapability) return dynamicCapability;
  return ROUTE_CAPABILITY_POLICIES.find((policy) => (
    policy.exact
      ? pathname === policy.prefix
      : pathname === policy.prefix || pathname.startsWith(`${policy.prefix}/`)
  ))?.capability ?? null;
}

export function canAccessApplicationPath(
  user: User | null | undefined,
  pathname: string,
): boolean {
  if (!user || !user.is_active) return false;
  const capability = resolveRouteCapability(pathname);
  if (!capability) return false;
  if (capability === "gc_app.manage") return canManageGcApp(user);
  return ROLE_CAPABILITIES[user.role].includes(capability);
}

export function firstAuthorizedPath(user: User): string {
  if (user.role === "agency_coordinator") return ROUTES.coordinator;
  if (OFFICE_ROLES.includes(user.role)) {
    if (canAccessApplicationPath(user, ROUTES.dashboard.root)) {
      return ROUTES.dashboard.root;
    }
    if (canAccessApplicationPath(user, ROUTES.dashboard.passports)) {
      return ROUTES.dashboard.passports;
    }
  }
  return ROUTES.auth.login;
}
