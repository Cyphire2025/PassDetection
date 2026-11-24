import { ROUTES } from "@/constants/routes";
import type { PassportGroupSubmissionFilter, PassportGroupSubmissionSort } from "../api/passports.api";

export type PassportGroupViewMode = "table" | "docs";

export interface PassportGroupViewState {
  search: string;
  submissionFilter: PassportGroupSubmissionFilter;
  sortBy: PassportGroupSubmissionSort;
  sortOrder: "asc" | "desc";
  page: number;
  viewMode: PassportGroupViewMode;
}

export interface PassportDetailNavigationState {
  token: string | null;
  groupId: string;
  includeDeleted: boolean;
  viewState: PassportGroupViewState;
}

const DEFAULT_VIEW_STATE: PassportGroupViewState = {
  search: "",
  submissionFilter: "all",
  sortBy: "name",
  sortOrder: "asc",
  page: 1,
  viewMode: "table",
};

const SUBMISSION_FILTERS = new Set<PassportGroupSubmissionFilter>([
  "all",
  "pending_ai",
  "ai_approved",
  "needs_review",
  "staff_approved",
  "duplicates",
  "document_follow_up",
]);

const SORT_FIELDS = new Set<PassportGroupSubmissionSort>([
  "name",
  "updated_at",
  "verification_confidence",
]);

const SORT_ORDERS = new Set<PassportGroupViewState["sortOrder"]>(["asc", "desc"]);

const VIEW_MODES = new Set<PassportGroupViewMode>(["table", "docs"]);

export const TOKEN_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type SearchParamsReader = Pick<URLSearchParams, "get">;

export function parsePassportGroupViewState(
  params: SearchParamsReader,
  prefix = "",
): PassportGroupViewState {
  return {
    search: (params.get(`${prefix}q`) ?? "").trim().slice(0, 200),
    submissionFilter: readEnum(
      params.get(`${prefix}filter`),
      SUBMISSION_FILTERS,
      DEFAULT_VIEW_STATE.submissionFilter,
    ),
    sortBy: readEnum(
      params.get(`${prefix}sort`),
      SORT_FIELDS,
      DEFAULT_VIEW_STATE.sortBy,
    ),
    sortOrder: readEnum(
      params.get(`${prefix}order`),
      SORT_ORDERS,
      DEFAULT_VIEW_STATE.sortOrder,
    ),
    page: readPositiveInteger(params.get(`${prefix}page`)),
    viewMode: readEnum(
      params.get(`${prefix}view`),
      VIEW_MODES,
      DEFAULT_VIEW_STATE.viewMode,
    ),
  };
}

export function buildPassportGroupHref(
  groupId: string,
  state: PassportGroupViewState,
  includeDeleted: boolean,
) {
  const params = serializeViewState(state);
  if (includeDeleted) params.set("old_data", "1");
  const query = params.toString();
  const pathname = ROUTES.dashboard.passportGroup(groupId);
  return query ? `${pathname}?${query}` as const : pathname;
}

export function buildPassportDetailNavigationHref(
  submissionId: string,
  navigation: PassportDetailNavigationState,
) {
  const params = serializeViewState(navigation.viewState, "nav_");
  params.set("nav_group", navigation.groupId);
  if (navigation.includeDeleted) params.set("nav_old_data", "1");
  if (navigation.token) params.set("nav", navigation.token);
  return `${ROUTES.dashboard.passportDetail(submissionId)}?${params.toString()}` as const;
}

export function parsePassportDetailNavigation(
  params: SearchParamsReader,
): PassportDetailNavigationState | null {
  const groupId = (params.get("nav_group") ?? "").trim();
  if (!isUuid(groupId)) return null;
  const tokenValue = (params.get("nav") ?? "").trim();
  return {
    token: TOKEN_PATTERN.test(tokenValue) ? tokenValue : null,
    groupId,
    includeDeleted: params.get("nav_old_data") === "1",
    viewState: parsePassportGroupViewState(params, "nav_"),
  };
}

function serializeViewState(state: PassportGroupViewState, prefix = "") {
  const params = new URLSearchParams();
  if (state.search) params.set(`${prefix}q`, state.search);
  if (state.submissionFilter !== DEFAULT_VIEW_STATE.submissionFilter) {
    params.set(`${prefix}filter`, state.submissionFilter);
  }
  if (state.sortBy !== DEFAULT_VIEW_STATE.sortBy) {
    params.set(`${prefix}sort`, state.sortBy);
  }
  if (state.sortOrder !== DEFAULT_VIEW_STATE.sortOrder) {
    params.set(`${prefix}order`, state.sortOrder);
  }
  if (state.page !== DEFAULT_VIEW_STATE.page) {
    params.set(`${prefix}page`, String(state.page));
  }
  if (state.viewMode !== DEFAULT_VIEW_STATE.viewMode) {
    params.set(`${prefix}view`, state.viewMode);
  }
  return params;
}

function readEnum<T extends string>(
  value: string | null,
  allowed: ReadonlySet<T>,
  fallback: T,
) {
  return value !== null && allowed.has(value as T) ? value as T : fallback;
}

function readPositiveInteger(value: string | null) {
  if (!value || !/^\d+$/.test(value)) return DEFAULT_VIEW_STATE.page;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 1 ? parsed : DEFAULT_VIEW_STATE.page;
}

export function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

export function isValidViewState(value: unknown): value is PassportGroupViewState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<PassportGroupViewState>;
  return (
    typeof state.search === "string"
    && state.search.length <= 200
    && SUBMISSION_FILTERS.has(state.submissionFilter as PassportGroupSubmissionFilter)
    && SORT_FIELDS.has(state.sortBy as PassportGroupSubmissionSort)
    && SORT_ORDERS.has(state.sortOrder as PassportGroupViewState["sortOrder"])
    && Number.isSafeInteger(state.page)
    && Number(state.page) >= 1
    && VIEW_MODES.has(state.viewMode as PassportGroupViewMode)
  );
}
