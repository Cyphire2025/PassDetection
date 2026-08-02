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
    coordinatorLogin: (from = "/coordinator") => `/login?from=${encodeURIComponent(from)}`,
  },

  dashboard: {
    root: "/dashboard",
    passports: "/passports",
    passportGroup: (groupId: string) => `/passports/groups/${groupId}`,
    passportGroupWhatsAppTracking: (groupId: string) =>
      `/passports/groups/${groupId}/whatsapp`,
    passportDetail: (id: string) => `/passports/${id}`,
    uploadLinks: "/upload-links",
    whatsapp: "/whatsapp",
    emailIntegrations: "/email-integrations",
    emailIntegrationsInbox: "/email-integrations/inbox",
    emailIntegrationsReview: "/email-integrations/review",
    emailIntegrationsActivity: "/email-integrations/activity",
    emailIntegrationMessage: (messageId: string) =>
      `/email-integrations/activity/${messageId}`,
    documents: "/documents",
    documentRename: "/documents/rename",
    documentDistribution: "/documents/distribution",
    documentGroup: (groupId: string) => `/documents/distribution/${groupId}`,
    tourOperations: "/tour-operations",
    tourOperationsCoordinators: "/tour-operations/coordinators",
    tourOperationsGroupAssignments: "/tour-operations/group-assignments",
    tourOperationsGroup: (groupId: string) => `/tour-operations/groups/${groupId}`,
    tourOperationsGroupAttendance: (groupId: string) => `/tour-operations/groups/${groupId}/attendance`,
    tourOperationsGroupQrCodes: (groupId: string) => `/tour-operations/groups/${groupId}/qr-codes`,
    tourOperationsScannerProof: "/tour-operations/scanner-proof",
    rooming: "/rooming",
    roomingGroup: (groupId: string) => `/rooming/${groupId}`,
    menu: "/menu",
    gcAppRoot: "/gc-app",
    gcAppClientManagerAccounts: "/gc-app/client-manager-accounts",
    gcAppAppControls: "/gc-app/app-controls",
    gcAppGroup: (groupId: string) => `/gc-app/app-controls/${groupId}`,
    admin: "/admin",
    staff: "/staff",
    analytics: "/analytics",
    auditLogs: "/audit-logs",
    settings: "/settings",
    oldData: "/old-data",
  },

  upload: {
    client: (token: string) => `/upload/${token}`,
  },
} as const;

export type AppRoute = string;
