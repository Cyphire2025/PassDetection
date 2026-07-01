/**
 * Application-wide constants
 * ==========================
 */

export const APP_NAME = "PassDetection";

export const PASSPORT_STATUS_LABELS: Record<string, string> = {
  pending_upload: "Pending Upload",
  uploaded: "Uploaded",
  processing: "Processing",
  review_required: "Review Required",
  client_submitted: "Client Submitted",
  confirmed: "Confirmed",
  failed: "Failed",
};

export const PASSPORT_STATUS_COLORS: Record<
  string,
  "default" | "secondary" | "destructive" | "outline" | "success" | "warning"
> = {
  pending_upload: "secondary",
  uploaded: "outline",
  processing: "secondary",
  review_required: "warning",
  client_submitted: "secondary",
  confirmed: "success",
  failed: "destructive",
};

export const UPLOAD_LINK_STATUS_LABELS: Record<string, string> = {
  active: "Active",
  used: "Used",
  expired: "Expired",
  revoked: "Revoked",
};

export const MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB
export const ACCEPTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"];

export const QUERY_KEYS = {
  passports: {
    all: ["passports"] as const,
    list: (params?: object) => ["passports", "list", params] as const,
    groups: (params?: object) => ["passports", "groups", params] as const,
    groupDetail: (groupId: string, params?: object) => ["passports", "groups", groupId, params] as const,
    detail: (id: string) => ["passports", "detail", id] as const,
  },
  operations: {
    adminOverview: ["operations", "admin-overview"] as const,
    managers: ["operations", "managers"] as const,
    analytics: (params?: object) => ["operations", "analytics", params] as const,
    auditLogs: (params?: object) => ["operations", "audit-logs", params] as const,
    notifications: (params?: object) => ["operations", "notifications", params] as const,
  },
  uploadLinks: {
    all: ["upload-links"] as const,
    list: (params?: object) => ["upload-links", "list", params] as const,
    detail: (id: string) => ["upload-links", "detail", id] as const,
    byToken: (token: string) => ["upload-links", "token", token] as const,
  },
  auth: {
    me: ["auth", "me"] as const,
  },
  dashboard: {
    stats: ["dashboard", "stats"] as const,
  },
} as const;
