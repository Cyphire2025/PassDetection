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
    admin: "/admin",
    analytics: "/analytics",
    auditLogs: "/audit-logs",
    notifications: "/notifications",
    settings: "/settings",
  },

  upload: {
    client: (token: string) => `/upload/${token}`,
  },
} as const;

export type AppRoute = string;
