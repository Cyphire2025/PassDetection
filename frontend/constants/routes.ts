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
    forgotPassword: "/forgot-password",
  },

  dashboard: {
    root: "/dashboard",
    passports: "/passports",
    passportGroup: (groupId: string) => `/passports/groups/${groupId}`,
    passportDetail: (id: string) => `/passports/${id}`,
    uploadLinks: "/upload-links",
    tourOperations: "/tour-operations",
    tourOperationsCoordinators: "/tour-operations/coordinators",
    tourOperationsGroupAssignments: "/tour-operations/group-assignments",
    tourOperationsGroup: (groupId: string) => `/tour-operations/groups/${groupId}`,
    tourOperationsGroupAttendance: (groupId: string) => `/tour-operations/groups/${groupId}/attendance`,
    tourOperationsGroupQrCodes: (groupId: string) => `/tour-operations/groups/${groupId}/qr-codes`,
    tourOperationsScannerProof: "/tour-operations/scanner-proof",
    admin: "/admin",
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
