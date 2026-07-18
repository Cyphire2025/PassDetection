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
    logoutAll: "/api/v1/auth/logout-all",
    refresh: "/api/v1/auth/refresh",
    me: "/api/v1/auth/me",
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
    telemetry: (token: string) =>
      `/api/v1/upload-links/token/${token}/telemetry`,
    qualifierSelection: (token: string) =>
      `/api/v1/upload-links/token/${token}/qualifier-selection`,
    revoke: (id: string) => `/api/v1/upload-links/${id}/revoke`,
    restore: (id: string) => `/api/v1/upload-links/${id}/restore`,
    delete: (id: string) => `/api/v1/upload-links/${id}`,
    permanentDelete: (id: string) => `/api/v1/upload-links/${id}/permanent`,
  },

  whatsapp: {
    groups: "/api/v1/whatsapp/groups",
    contactsPreview: "/api/v1/whatsapp/contacts/preview",
    group: (groupId: string) => `/api/v1/whatsapp/groups/${groupId}`,
    recipients: (groupId: string) => `/api/v1/whatsapp/groups/${groupId}/recipients`,
    recipient: (groupId: string, recipientId: string) =>
      `/api/v1/whatsapp/groups/${groupId}/recipients/${recipientId}`,
    preview: (groupId: string) => `/api/v1/whatsapp/groups/${groupId}/preview`,
    send: (groupId: string) => `/api/v1/whatsapp/groups/${groupId}/send`,
    batch: (batchId: string) => `/api/v1/whatsapp/batches/${batchId}`,
  },

  passports: {
    root: "/api/v1/passports",
    groups: "/api/v1/passports/groups",
    groupsExport: "/api/v1/passports/groups/export.xlsx",
    groupDetail: (groupId: string) => `/api/v1/passports/groups/${groupId}`,
    groupExport: (groupId: string) => `/api/v1/passports/groups/${groupId}/export.xlsx`,
    groupImageExport: (groupId: string) => `/api/v1/passports/groups/${groupId}/export-images`,
    groupImport: (groupId: string) => `/api/v1/passports/groups/${groupId}/import.xlsx`,
    passportDocumentPreview: (groupId: string) => `/api/v1/passports/groups/${groupId}/import-passports/preview`,
    passportDocumentSave: (groupId: string) => `/api/v1/passports/groups/${groupId}/import-passports/save`,
    selectedExport: "/api/v1/passports/export.xlsx",
    detail: (id: string) => `/api/v1/passports/${id}`,
    upload: (token: string) => `/api/v1/passports/upload/${token}`,
    reconcileUpload: (token: string) => `/api/v1/passports/upload/${token}`,
    uploadStatus: (token: string, id: string) => `/api/v1/passports/upload/${token}/${id}/status`,
    uploadImage: (token: string, id: string) => `/api/v1/passports/upload/${token}/${id}/image`,
    uploadDocumentImage: (
      token: string,
      id: string,
      documentType: "front" | "back" | "photo",
    ) => `/api/v1/passports/upload/${token}/${id}/image/${documentType}`,
    uploadScanAgain: (token: string, id: string) => `/api/v1/passports/upload/${token}/${id}/scan-again`,
    discardUpload: (token: string, id: string) => `/api/v1/passports/upload/${token}/${id}`,
    confirm: (id: string) => `/api/v1/passports/${id}/confirm`,
    staffApprove: (id: string) => `/api/v1/passports/${id}/staff-approve`,
    retryAiVerification: (id: string) => `/api/v1/passports/${id}/retry-ai-verification`,
    clientSubmit: (id: string) => `/api/v1/passports/${id}/client-submit`,
    reextract: (id: string) => `/api/v1/passports/${id}/reextract`,
    cancelProcessing: (id: string) => `/api/v1/passports/${id}/cancel-processing`,
  },

  documents: {
    groups: "/api/v1/document-distribution/groups",
    review: (groupId: string, documentType: string) => `/api/v1/document-distribution/groups/${groupId}/${documentType}`,
    verify: (groupId: string, documentType: string) => `/api/v1/document-distribution/groups/${groupId}/${documentType}/verify`,
    upload: (groupId: string, documentType: string) => `/api/v1/document-distribution/groups/${groupId}/${documentType}/upload`,
    reupload: (groupId: string, documentType: string, passengerId: string) =>
      `/api/v1/document-distribution/groups/${groupId}/${documentType}/passengers/${passengerId}/reupload`,
    deleteDocuments: (groupId: string, documentType: string) =>
      `/api/v1/document-distribution/groups/${groupId}/${documentType}/documents/delete`,
    saveBatch: (batchId: string) => `/api/v1/document-distribution/batches/${batchId}/save`,
  },

  documentRename: {
    batches: "/api/v1/document-rename/batches",
    bulkDelete: "/api/v1/document-rename/batches/bulk-delete",
    batch: (batchId: string) => `/api/v1/document-rename/batches/${batchId}`,
    itemDownload: (itemId: string) => `/api/v1/document-rename/items/${itemId}/download`,
    zipDownload: (batchId: string) => `/api/v1/document-rename/batches/${batchId}/download.zip`,
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
    passengerQr: (groupId: string, passengerId: string) =>
      `/api/v1/tour-operations/groups/${groupId}/passengers/${passengerId}/qr`,
    passengerQrRegenerate: (groupId: string, passengerId: string) =>
      `/api/v1/tour-operations/groups/${groupId}/passengers/${passengerId}/qr/regenerate`,
    passengerQrRevoke: (groupId: string, passengerId: string) =>
      `/api/v1/tour-operations/groups/${groupId}/passengers/${passengerId}/qr/revoke`,
    passengerQrActive: (groupId: string, passengerId: string) =>
      `/api/v1/tour-operations/groups/${groupId}/passengers/${passengerId}/qr/active`,
    passengerQrExpiration: (groupId: string, passengerId: string) =>
      `/api/v1/tour-operations/groups/${groupId}/passengers/${passengerId}/qr/expiration`,
    myGroups: "/api/v1/tour-operations/coordinator/groups",
    myGroupPassengers: (groupId: string) => `/api/v1/tour-operations/coordinator/groups/${groupId}/passengers`,
    myGroupPassenger: (groupId: string, passengerId: string) =>
      `/api/v1/tour-operations/coordinator/groups/${groupId}/passengers/${passengerId}`,
    myGroupSessions: (groupId: string) => `/api/v1/tour-operations/coordinator/groups/${groupId}/sessions`,
    mySessionDetails: (sessionId: string) => `/api/v1/tour-operations/coordinator/sessions/${sessionId}/details`,
    mySessionScan: (sessionId: string) => `/api/v1/tour-operations/coordinator/sessions/${sessionId}/scan`,
    mySessionComplete: (sessionId: string) => `/api/v1/tour-operations/coordinator/sessions/${sessionId}/complete`,
  },

  rooming: {
    group: (groupId: string) => `/api/v1/rooming/groups/${groupId}`,
    hotels: (groupId: string) => `/api/v1/rooming/groups/${groupId}/hotels`,
    hotel: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}`,
    generateRooms: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/rooms/generate`,
    hotelExport: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/export.xlsx`,
    checkins: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/check-ins`,
    checkinScan: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/check-ins/scan`,
    checkinExport: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/check-ins/export.xlsx`,
    checkin: (checkinId: string) => `/api/v1/rooming/check-ins/${checkinId}`,
    room: (roomId: string) => `/api/v1/rooming/rooms/${roomId}`,
    roomOrder: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/rooms/order`,
    allocation: (hotelId: string, passengerId: string) =>
      `/api/v1/rooming/hotels/${hotelId}/passengers/${passengerId}/allocation`,
  },

  admin: {
    overview: "/api/v1/admin/overview",
    managers: "/api/v1/admin/managers",
    manager: (managerId: string) => `/api/v1/admin/managers/${managerId}`,
    staffAccess: "/api/v1/admin/staff",
    staffGroups: (staffId: string) => `/api/v1/admin/staff/${staffId}/groups`,
    groups: "/api/v1/admin/groups",
    managerGroups: (managerId: string) => `/api/v1/admin/managers/${managerId}/groups`,
    accounts: "/api/v1/admin/accounts",
    staff: "/api/v1/admin/accounts/staff",
    account: (accountId: string) => `/api/v1/admin/accounts/${accountId}`,
    accountPassword: (accountId: string) => `/api/v1/admin/accounts/${accountId}/reset-password`,
    accountSessions: (accountId: string) => `/api/v1/admin/accounts/${accountId}/revoke-sessions`,
    accountStatus: (accountId: string) => `/api/v1/admin/accounts/${accountId}/status`,
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
