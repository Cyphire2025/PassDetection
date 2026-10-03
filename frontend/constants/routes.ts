import type { Route } from "next";

/**
 * Application Routes
 * ==================
 * Single source of truth for all route paths.
 * Never hardcode paths in components — always import from here.
 *
 * Usage:
 *   import { ROUTES } from "@/constants/routes"
 *   router.push(ROUTES.dashboard.root)
 */

export const ROUTES = {
  root: "/",
  coordinator: "/coordinator",
  tourScanner: "/tour-scanner",

  auth: {
    login: "/login",
    coordinatorLogin: (from = "/coordinator") => `/login?from=${encodeURIComponent(from)}` as const,
  },

  dashboard: {
    root: "/dashboard",
    passports: "/passports",
    passportGroup: (groupId: string) => `/passports/groups/${encodeURIComponent(groupId)}` as const,
    passportGroupWhatsAppTracking: (groupId: string) =>
      `/passports/groups/${encodeURIComponent(groupId)}/whatsapp` as const,
    passportDetail: (id: string) => `/passports/${encodeURIComponent(id)}` as const,
    uploadLinks: "/upload-links",
    whatsapp: "/whatsapp",
    emailIntegrations: "/email-integrations",
    emailIntegrationsInbox: "/email-integrations/inbox",
    emailIntegrationsReview: "/email-integrations/review",
    emailIntegrationsActivity: "/email-integrations/activity",
    emailIntegrationMessage: (messageId: string) =>
      `/email-integrations/activity/${encodeURIComponent(messageId)}` as const,
    documents: "/documents",
    travelTracker: "/documents/tracker",
    travelTrackerGroup: (groupId: string) => `/documents/tracker/${encodeURIComponent(groupId)}` as const,
    documentRename: "/documents/rename",
    ecrChecker: "/documents/ecr-checker",
    documentDistribution: "/documents/distribution",
    documentDistributionVisa: "/documents/distribution/visa",
    documentDistributionVisaGroup: (groupId: string) =>
      `/documents/distribution/visa/${encodeURIComponent(groupId)}` as const,
    documentDistributionFlightTickets: "/documents/distribution/flight-tickets",
    documentDistributionFlightGroup: (groupId: string) =>
      `/documents/distribution/flight-tickets/${encodeURIComponent(groupId)}` as const,
    documentDistributionFlightLane: (
      groupId: string,
      scope: "international" | "domestic",
      leg: "onward" | "return",
    ) => `/documents/distribution/flight-tickets/${encodeURIComponent(groupId)}/${scope}/${leg}` as const,
    // Backwards-compatible group entry for notifications and linked workflows.
    documentGroup: (groupId: string) => `/documents/distribution/${encodeURIComponent(groupId)}` as const,
    tourOperations: "/tour-operations",
    tourOperationsCoordinators: "/tour-operations/coordinators",
    tourOperationsGroupAssignments: "/tour-operations/group-assignments",
    tourOperationsGroup: (groupId: string) => `/tour-operations/groups/${encodeURIComponent(groupId)}` as const,
    tourOperationsGroupAttendance: (groupId: string) => `/tour-operations/groups/${encodeURIComponent(groupId)}/attendance` as const,
    tourOperationsGroupQrCodes: (groupId: string) => `/tour-operations/groups/${encodeURIComponent(groupId)}/qr-codes` as const,
    tourOperationsScannerProof: "/tour-operations/scanner-proof",
    rooming: "/rooming",
    roomingGroup: (groupId: string) => `/rooming/${encodeURIComponent(groupId)}` as const,
    menu: "/menu",
    gcAppRoot: "/gc-app",
    gcAppClientManagerAccounts: "/gc-app/client-manager-accounts",
    gcAppAppControls: "/gc-app/app-controls",
    gcAppNotifications: "/gc-app/notifications",
    gcAppGroup: (groupId: string) => `/gc-app/app-controls/${encodeURIComponent(groupId)}` as const,
    admin: "/admin",
    mcp: "/admin/mcp",
    mcpConnect: "/admin/mcp/connect",
    staff: "/staff",
    analytics: "/analytics",
    auditLogs: "/audit-logs",
    settings: "/settings",
    oldData: "/old-data",
  },

  upload: {
    client: (token: string) => `/upload/${encodeURIComponent(token)}` as const,
  },
} as const;

export type AppRoute = Route;
