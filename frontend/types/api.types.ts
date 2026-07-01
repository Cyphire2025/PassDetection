/**
 * Global API Types
 * ================
 * These types mirror the backend's response envelope exactly.
 * Any change to the backend API contract must be reflected here.
 */

// ── Error Envelope ────────────────────────────────────────────────────────────

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>[];
}

export interface ApiErrorResponse {
  error: ApiError;
}

// ── Pagination ────────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}

export interface PaginationParams {
  skip?: number;
  limit?: number;
}

// ── Common Fields ─────────────────────────────────────────────────────────────

export interface TimestampedEntity {
  created_at: string;   // ISO 8601
  updated_at: string;
}
