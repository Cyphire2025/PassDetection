import { afterEach, expect, it, vi } from "vitest";
import {
  buildPassportDetailNavigationHref,
  buildPassportGroupHref,
  parsePassportDetailNavigation,
  parsePassportGroupViewState,
  readPassportNavigationContext,
  storePassportNavigationContext,
} from "./passport-group-navigation";

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });
const context = { token: "aeb87f17-dfb9-4025-924f-a6d601d1a9b4", userId: "d4280387-4cf1-49b4-b2d5-e57ff8dc5b79", groupId: "f2723f82-d09a-4eb5-a5ee-ad5ea0ba10a3" };
it("falls back to server navigation when session storage itself is denied", () => {
  vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
  expect(readPassportNavigationContext(context)).toBeNull();
});
it("does not let a failed cleanup mask invalid stored navigation", () => {
  vi.spyOn(Storage.prototype, "getItem").mockReturnValue("invalid-json");
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
  expect(readPassportNavigationContext(context)).toBeNull();
});

const viewState = { search: "Synthetic traveller", submissionFilter: "needs_review" as const, sortBy: "updated_at" as const, sortOrder: "desc" as const, page: 3, viewMode: "docs" as const };
const submissionId = "8659e8db-a71f-4274-b315-261a766f7bf9";
const storageKey = `passdetection:passport-navigation:${context.userId}:${context.token}`;

it("round-trips the current view and old-data scope through both route forms", () => {
  const group = new URL(buildPassportGroupHref(context.groupId, viewState, true), "https://synthetic.test");
  expect(group.searchParams.get("old_data")).toBe("1");
  expect(parsePassportGroupViewState(group.searchParams)).toEqual(viewState);
  const detail = new URL(buildPassportDetailNavigationHref(submissionId, { ...context, includeDeleted: true, viewState }), "https://synthetic.test");
  expect(parsePassportDetailNavigation(detail.searchParams)).toEqual({ token: context.token, groupId: context.groupId, includeDeleted: true, viewState });
});

it("bounds untrusted query state and rejects an invalid navigation identity", () => {
  const parsed = parsePassportGroupViewState(new URLSearchParams({ q: "x".repeat(250), filter: "invented", sort: "secret", order: "up", page: "9007199254740992", view: "external" }));
  expect(parsed).toEqual({ search: "x".repeat(200), submissionFilter: "all", sortBy: "name", sortOrder: "asc", page: 1, viewMode: "table" });
  expect(parsePassportDetailNavigation(new URLSearchParams({ nav_group: "invalid" }))).toBeNull();
  expect(parsePassportDetailNavigation(new URLSearchParams({ nav_group: context.groupId, nav: "invalid" }))?.token).toBeNull();
});

it("stores only a snapshot of the admitted order and refuses another actor or group", () => {
  const ids = [submissionId];
  expect(storePassportNavigationContext({ ...context, includeDeleted: false, viewState, orderedSubmissionIds: ids })).toBe(true);
  ids.push(context.groupId);
  expect(readPassportNavigationContext(context)?.orderedSubmissionIds).toEqual([submissionId]);
  expect(readPassportNavigationContext({ ...context, userId: submissionId })).toBeNull();
  expect(readPassportNavigationContext({ ...context, groupId: submissionId })).toBeNull();
});

it("expires the user-bound navigation context without changing the fallback route metadata", () => {
  const now = Date.now();
  vi.spyOn(Date, "now").mockReturnValue(now);
  storePassportNavigationContext({ ...context, includeDeleted: false, viewState, orderedSubmissionIds: [submissionId] });
  vi.spyOn(Date, "now").mockReturnValue(now + 12 * 60 * 60 * 1000 + 1);
  expect(readPassportNavigationContext(context)).toBeNull();
  expect(sessionStorage.getItem(storageKey)).toBeNull();
  expect(parsePassportGroupViewState(new URLSearchParams({ q: viewState.search }))).toMatchObject({ search: viewState.search });
});

it("fails closed for malformed stored order or view state and cleans only that context", () => {
  vi.spyOn(Date, "now").mockReturnValue(Date.now());
  const stored = { ...context, includeDeleted: false, viewState, orderedSubmissionIds: [submissionId], version: 1, createdAt: Date.now() };
  const otherKey = `passdetection:passport-navigation:${submissionId}:unrelated`;
  sessionStorage.setItem(otherKey, "unrelated metadata");
  for (const patch of [{ orderedSubmissionIds: ["invalid"] }, { orderedSubmissionIds: Array(10_001).fill(submissionId) }, { viewState: { ...viewState, page: 0 } }, { createdAt: Date.now() + 60_001 }]) {
    sessionStorage.setItem(storageKey, JSON.stringify({ ...stored, ...patch }));
    expect(readPassportNavigationContext(context)).toBeNull();
    expect(sessionStorage.getItem(storageKey)).toBeNull();
    expect(sessionStorage.getItem(otherKey)).toBe("unrelated metadata");
  }
});
