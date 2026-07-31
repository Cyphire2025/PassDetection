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

  notifications: {
    feed: "/api/v1/notifications/feed",
    read: (notificationId: string) =>
      `/api/v1/notifications/${encodeURIComponent(notificationId)}/read`,
    readAll: "/api/v1/notifications/read-all",
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
    whatsappBroadcastOptions: "/api/v1/upload-links/whatsapp-broadcast-options",
    groupWhatsAppBroadcastOptions: (id: string) =>
      `/api/v1/upload-links/${id}/whatsapp-broadcast-options`,
    whatsappLinks: (id: string) => `/api/v1/upload-links/${id}/whatsapp-links`,
    whatsappMatches: (id: string) => `/api/v1/upload-links/${id}/whatsapp-matches`,
    replacementCandidates: (id: string) =>
      `/api/v1/upload-links/${id}/replacement-candidates`,
    resolveUnidentifiedReplacement: (id: string, submissionId: string) =>
      `/api/v1/upload-links/${id}/unidentified/${submissionId}/replacement`,
    rejectUnidentifiedUpload: (id: string, submissionId: string) =>
      `/api/v1/upload-links/${id}/unidentified/${submissionId}/reject`,
    restoreRosterResolution: (id: string, resolutionId: string) =>
      `/api/v1/upload-links/${id}/roster-resolutions/${resolutionId}/restore`,
  },

  whatsapp: {
    groups: "/api/v1/whatsapp/groups",
    contactsPreview: "/api/v1/whatsapp/contacts/preview",
    group: (groupId: string) => `/api/v1/whatsapp/groups/${groupId}`,
    recipients: (groupId: string) => `/api/v1/whatsapp/groups/${groupId}/recipients`,
    rejectedContacts: (groupId: string) =>
      `/api/v1/whatsapp/groups/${groupId}/rejected-contacts`,
    recipientRoster: (groupId: string) =>
      `/api/v1/whatsapp/groups/${groupId}/recipient-roster`,
    resolveRejectedContact: (groupId: string, rejectedContactId: string) =>
      `/api/v1/whatsapp/groups/${groupId}/rejected-contacts/${rejectedContactId}/resolve`,
    recipient: (groupId: string, recipientId: string) =>
      `/api/v1/whatsapp/groups/${groupId}/recipients/${recipientId}`,
    resendRecipientMessage: (groupId: string, recipientId: string) =>
      `/api/v1/whatsapp/groups/${groupId}/recipients/${recipientId}/resend`,
    preview: (groupId: string) => `/api/v1/whatsapp/groups/${groupId}/preview`,
    welcomeMedia: (groupId: string) =>
      `/api/v1/whatsapp/groups/${groupId}/welcome-media`,
    send: (groupId: string) => `/api/v1/whatsapp/groups/${groupId}/send`,
    batch: (batchId: string) => `/api/v1/whatsapp/batches/${batchId}`,
  },

  emailIntegrations: {
    status: "/api/v1/email-integrations/status",
    connections: "/api/v1/email-integrations/connections",
    gmailAuthorize: "/api/v1/email-integrations/oauth/gmail/authorize",
    outlookAuthorize: "/api/v1/email-integrations/oauth/outlook/authorize",
    connectionSync: (connectionId: string) =>
      `/api/v1/email-integrations/connections/${connectionId}/sync`,
    connectionPause: (connectionId: string) =>
      `/api/v1/email-integrations/connections/${connectionId}/pause`,
    connectionResume: (connectionId: string) =>
      `/api/v1/email-integrations/connections/${connectionId}/resume`,
    connectionAiSettings: (connectionId: string) =>
      `/api/v1/email-integrations/connections/${connectionId}/ai-settings`,
    connection: (connectionId: string) =>
      `/api/v1/email-integrations/connections/${connectionId}`,
    summary: "/api/v1/email-integrations/summary",
    inbox: "/api/v1/email-integrations/inbox",
    reviews: "/api/v1/email-integrations/reviews",
    reviewOptions: "/api/v1/email-integrations/review-options",
    resolveReview: (reviewId: string) =>
      `/api/v1/email-integrations/reviews/${reviewId}/resolve`,
    activity: "/api/v1/email-integrations/activity",
    message: (messageId: string) =>
      `/api/v1/email-integrations/messages/${messageId}`,
    messageIntelligence: (messageId: string) =>
      `/api/v1/email-integrations/messages/${messageId}/intelligence`,
    proposalDecision: (proposalId: string) =>
      `/api/v1/email-integrations/proposals/${proposalId}/decision`,
    deadlineDecision: (deadlineId: string) =>
      `/api/v1/email-integrations/deadlines/${deadlineId}/decision`,
    draft: (draftId: string) =>
      `/api/v1/email-integrations/drafts/${draftId}`,
    draftDecision: (draftId: string) =>
      `/api/v1/email-integrations/drafts/${draftId}/decision`,
    analysisFeedback: (analysisId: string) =>
      `/api/v1/email-integrations/analyses/${analysisId}/feedback`,
    analysisRetry: (analysisId: string) =>
      `/api/v1/email-integrations/analyses/${analysisId}/retry`,
  },

  passports: {
    root: "/api/v1/passports",
    groups: "/api/v1/passports/groups",
    groupSummaries: "/api/v1/passports/groups/summaries",
    groupSummary: (groupId: string) =>
      `/api/v1/passports/groups/${groupId}/summary`,
    groupsExport: "/api/v1/passports/groups/export.xlsx",
    groupsExportFields: "/api/v1/passports/groups/export-fields",
    groupDetail: (groupId: string) => `/api/v1/passports/groups/${groupId}`,
    groupSubmissionsView: (groupId: string) =>
      `/api/v1/passports/groups/${groupId}/submissions-view`,
    groupExport: (groupId: string) => `/api/v1/passports/groups/${groupId}/export.xlsx`,
    groupWhatsAppTrackingExport: (groupId: string) =>
      `/api/v1/passports/groups/${groupId}/whatsapp-tracking/export.xlsx`,
    groupExportFields: (groupId: string) =>
      `/api/v1/passports/groups/${groupId}/export-fields`,
    groupImageExport: (groupId: string) => `/api/v1/passports/groups/${groupId}/export-images`,
    groupSelectedImageExport: (groupId: string) =>
      `/api/v1/passports/groups/${groupId}/export-images/selected`,
    groupExportHistory: (groupId: string) =>
      `/api/v1/passports/groups/${groupId}/export-history`,
    groupExportHistoryDetail: (groupId: string, historyId: string) =>
      `/api/v1/passports/groups/${groupId}/export-history/${historyId}`,
    groupExportHistoryComplete: (groupId: string, historyId: string) =>
      `/api/v1/passports/groups/${groupId}/export-history/${historyId}/complete`,
    groupImport: (groupId: string) => `/api/v1/passports/groups/${groupId}/import.xlsx`,
    passportDocumentPreview: (groupId: string) => `/api/v1/passports/groups/${groupId}/import-passports/preview`,
    passportDocumentSave: (groupId: string) => `/api/v1/passports/groups/${groupId}/import-passports/save`,
    bulkDelete: (groupId: string) => `/api/v1/passports/groups/${groupId}/bulk-delete`,
    selectedExport: "/api/v1/passports/export.xlsx",
    detail: (id: string) => `/api/v1/passports/${id}`,
    imageCrop: (
      id: string,
      imageType: "visa_photo" | "passport_front" | "passport_back",
    ) => `/api/v1/passports/${id}/images/${imageType}/crop`,
    currentImage: (
      id: string,
      imageType: "visa_photo" | "passport_front" | "passport_back",
    ) => `/api/v1/passports/${id}/images/${imageType}`,
    originalImage: (
      id: string,
      imageType: "visa_photo" | "passport_front" | "passport_back",
    ) => `/api/v1/passports/${id}/images/${imageType}/original`,
    imageLibrary: (
      id: string,
      imageType: "visa_photo" | "passport_front" | "passport_back",
    ) => `/api/v1/passports/${id}/images/${imageType}/library`,
    imageLibraryUse: (
      id: string,
      imageType: "visa_photo" | "passport_front" | "passport_back",
      itemId: string,
    ) => `/api/v1/passports/${id}/images/${imageType}/library/${itemId}/use`,
    visaAiPreview: (id: string) =>
      `/api/v1/passports/${id}/images/visa_photo/ai-preview`,
    visaAiApply: (id: string) =>
      `/api/v1/passports/${id}/images/visa_photo/ai-apply`,
    visaAiLibrary: (id: string) =>
      `/api/v1/passports/${id}/images/visa_photo/ai-library`,
    visaAiLibraryUse: (id: string, generationId: string) =>
      `/api/v1/passports/${id}/images/visa_photo/ai-library/${generationId}/use`,
    visaAiJobs: (id: string) =>
      `/api/v1/passports/${id}/images/visa_photo/ai-jobs`,
    visaAiActiveJob: (id: string) =>
      `/api/v1/passports/${id}/images/visa_photo/ai-jobs/active`,
    visaAiJob: (id: string, jobId: string) =>
      `/api/v1/passports/${id}/images/visa_photo/ai-jobs/${jobId}`,
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
    unassignDocuments: (groupId: string, documentType: string) =>
      `/api/v1/document-distribution/groups/${groupId}/${documentType}/documents/unassign`,
    saveBatch: (batchId: string) => `/api/v1/document-distribution/batches/${batchId}/save`,
    whatsappPreview: (groupId: string, documentType: string) =>
      `/api/v1/document-distribution/groups/${groupId}/${documentType}/whatsapp-preview`,
    sendWhatsApp: (batchId: string) =>
      `/api/v1/document-distribution/batches/${batchId}/whatsapp-send`,
    deliveryTracking: (groupId: string) =>
      `/api/v1/document-distribution/groups/${groupId}/whatsapp-deliveries/tracking`,
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
    groupQrWhatsAppPreview: (groupId: string) =>
      `/api/v1/tour-operations/groups/${groupId}/qr-codes/whatsapp-preview`,
    groupQrWhatsAppSend: (groupId: string) =>
      `/api/v1/tour-operations/groups/${groupId}/qr-codes/whatsapp-send`,
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
    priorityFields: (groupId: string) => `/api/v1/rooming/groups/${groupId}/priority-fields`,
    hotels: (groupId: string) => `/api/v1/rooming/groups/${groupId}/hotels`,
    hotel: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}`,
    passengerSelection: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/passenger-selection`,
    vip: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/vip`,
    autoAllocate: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/auto-allocate`,
    hotelExport: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/export.xlsx`,
    checkins: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/check-ins`,
    checkinScan: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/check-ins/scan`,
    checkinExport: (hotelId: string) => `/api/v1/rooming/hotels/${hotelId}/check-ins/export.xlsx`,
    checkin: (checkinId: string) => `/api/v1/rooming/check-ins/${checkinId}`,
  },

  menu: {
    workspace: "/api/v1/menu",
    categories: "/api/v1/menu/categories",
    category: (categoryId: string) => `/api/v1/menu/categories/${categoryId}`,
    categoryDishes: (categoryId: string) =>
      `/api/v1/menu/categories/${categoryId}/dishes`,
    dish: (dishId: string) => `/api/v1/menu/dishes/${dishId}`,
    generatePlan: "/api/v1/menu/plans/generate",
    plan: (planId: string) => `/api/v1/menu/plans/${planId}`,
    regeneratePlan: (planId: string) =>
      `/api/v1/menu/plans/${planId}/regenerate`,
    planEntry: (planId: string, entryId: string) =>
      `/api/v1/menu/plans/${planId}/entries/${entryId}`,
    planExport: (planId: string) =>
      `/api/v1/menu/plans/${planId}/export.xlsx`,
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
    emailAiRollout: "/api/v1/admin/email-ai-rollout",
  },

  analytics: {
    summary: "/api/v1/analytics/summary",
  },

  auditLogs: {
    root: "/api/v1/audit-logs",
  },

} as const;
