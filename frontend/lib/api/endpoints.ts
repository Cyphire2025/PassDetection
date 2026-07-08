/**
 * API Endpoints Registry
 * ======================
 * All backend API endpoints in one file.
 * Never hardcode URLs inside hooks or components.
 *
 * Usage:
 *   import { API_ENDPOINTS } from "@/lib/api/endpoints"
 *   apiClient.get(API_ENDPOINTS.passports.list)
 */

export const API_ENDPOINTS = {
  health: {
    live: "/api/v1/health/live",
    ready: "/api/v1/health/ready",
  },

  dashboard: {
    stats: "/api/v1/dashboard/stats",
  },

  search: {
    global: "/api/v1/search",
  },

  auth: {
    login: "/api/v1/auth/login",
    logout: "/api/v1/auth/logout",
    refresh: "/api/v1/auth/refresh",
    me: "/api/v1/auth/me",
    forgotPassword: "/api/v1/auth/forgot-password",
    resetPassword: "/api/v1/auth/reset-password",
  },

  agencies: {
    root: "/api/v1/agencies",
    detail: (id: string) => `/api/v1/agencies/${id}`,
  },

  users: {
    root: "/api/v1/users",
    detail: (id: string) => `/api/v1/users/${id}`,
    me: "/api/v1/users/me",
  },

  uploadLinks: {
    root: "/api/v1/upload-links",
    detail: (id: string) => `/api/v1/upload-links/${id}`,
    byToken: (token: string) => `/api/v1/upload-links/token/${token}`,
    revoke: (id: string) => `/api/v1/upload-links/${id}/revoke`,
    restore: (id: string) => `/api/v1/upload-links/${id}/restore`,
    delete: (id: string) => `/api/v1/upload-links/${id}`,
    permanentDelete: (id: string) => `/api/v1/upload-links/${id}/permanent`,
  },

  passports: {
    root: "/api/v1/passports",
    groups: "/api/v1/passports/groups",
    groupsExport: "/api/v1/passports/groups/export.xlsx",
    groupDetail: (groupId: string) => `/api/v1/passports/groups/${groupId}`,
    groupExport: (groupId: string) => `/api/v1/passports/groups/${groupId}/export.xlsx`,
    selectedExport: "/api/v1/passports/export.xlsx",
    detail: (id: string) => `/api/v1/passports/${id}`,
    upload: (token: string) => `/api/v1/passports/upload/${token}`,
    uploadStatus: (token: string, id: string) => `/api/v1/passports/upload/${token}/${id}/status`,
    uploadImage: (token: string, id: string) => `/api/v1/passports/upload/${token}/${id}/image`,
    uploadScanAgain: (token: string, id: string) => `/api/v1/passports/upload/${token}/${id}/scan-again`,
    discardUpload: (token: string, id: string) => `/api/v1/passports/upload/${token}/${id}`,
    confirm: (id: string) => `/api/v1/passports/${id}/confirm`,
    clientSubmit: (id: string) => `/api/v1/passports/${id}/client-submit`,
    reextract: (id: string) => `/api/v1/passports/${id}/reextract`,
    cancelProcessing: (id: string) => `/api/v1/passports/${id}/cancel-processing`,
  },

  tourOperations: {
    architecture: "/api/v1/tour-operations/architecture",
    coordinators: "/api/v1/tour-operations/coordinators",
    groups: "/api/v1/tour-operations/groups",
    groupCoordinators: (groupId: string) => `/api/v1/tour-operations/groups/${groupId}/coordinators`,
    groupPassengers: (groupId: string) => `/api/v1/tour-operations/groups/${groupId}/passengers`,
    assignGroupPassengers: (groupId: string) => `/api/v1/tour-operations/groups/${groupId}/passengers/assign`,
    groupAttendance: (groupId: string) => `/api/v1/tour-operations/groups/${groupId}/attendance`,
    groupQrCodes: (groupId: string) => `/api/v1/tour-operations/groups/${groupId}/qr-codes`,
    myGroups: "/api/v1/tour-operations/coordinator/groups",
    myGroupPassengers: (groupId: string) => `/api/v1/tour-operations/coordinator/groups/${groupId}/passengers`,
    myGroupSessions: (groupId: string) => `/api/v1/tour-operations/coordinator/groups/${groupId}/sessions`,
    mySessionScan: (sessionId: string) => `/api/v1/tour-operations/coordinator/sessions/${sessionId}/scan`,
    mySessionComplete: (sessionId: string) => `/api/v1/tour-operations/coordinator/sessions/${sessionId}/complete`,
  },

  admin: {
    overview: "/api/v1/admin/overview",
    managers: "/api/v1/admin/managers",
    manager: (managerId: string) => `/api/v1/admin/managers/${managerId}`,
    groups: "/api/v1/admin/groups",
    managerGroups: (managerId: string) => `/api/v1/admin/managers/${managerId}/groups`,
    settings: "/api/v1/admin/settings",
    passportData: "/api/v1/admin/passport-data",
  },

  analytics: {
    summary: "/api/v1/analytics/summary",
  },

  auditLogs: {
    root: "/api/v1/audit-logs",
  },

} as const;
