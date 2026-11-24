export interface AnalyticsSummary {
  status_counts: Record<string, number>;
  confidence_buckets: Record<string, number>;
  submissions_by_day: Record<string, number>;
  average_confidence: number | null;
}

export interface AuditLogListItem {
  id: string;
  agency_id: string | null;
  user_id: string | null;
  actor_email: string | null;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  result: AuditLogResult | null;
  created_at: string;
}

export type AuditLogResult = "success" | "blocked" | "denied" | "failed";

export interface AuditLogPage {
  items: AuditLogListItem[];
  has_more: boolean;
  next_cursor: string | null;
  incomplete: boolean;
  page_size: number;
}

export interface AuditLogFilters {
  start_at?: string;
  end_at?: string;
  actor?: string;
  event_type?: string;
  entity_type?: string;
  entity_id?: string;
  result?: AuditLogResult;
  agency_id?: string;
}
