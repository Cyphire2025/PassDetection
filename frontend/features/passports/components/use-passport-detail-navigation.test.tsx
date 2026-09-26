import { act, fireEvent, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePassportDetailNavigation } from "./use-passport-detail-navigation";
import { storePassportNavigationContext } from "../utils/passport-group-navigation";

const { push, view } = vi.hoisted(() => ({ push: vi.fn(), view: vi.fn<(group: string, params: unknown, enabled: boolean) => { data: { ordered_submission_ids: string[] } }>(() => ({ data: { ordered_submission_ids: ["server-id"] } })) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("../hooks/use-passports", () => ({ useGroupSubmissionsView: view }));

const groupId = "f2723f82-d09a-4eb5-a5ee-ad5ea0ba10a3";
const userId = "d4280387-4cf1-49b4-b2d5-e57ff8dc5b79";
const token = "aeb87f17-dfb9-4025-924f-a6d601d1a9b4";
const ordered = ["9cf90b72-2af6-47f4-b2ea-cbbcfb6a43d3", "92b64d8e-cf9e-4a26-8f09-97d5a0279fc6", "0f34b09f-d8ac-4933-bcb9-727afad61ef1"];
const query = `nav_group=${groupId}&nav=${token}&nav_q=searched&nav_page=2`;
beforeEach(() => {
  push.mockClear(); view.mockClear(); window.sessionStorage.clear();
  storePassportNavigationContext({ token, userId, groupId, orderedSubmissionIds: ordered, includeDeleted: false,
    viewState: { search: "searched", submissionFilter: "all", sortBy: "name", sortOrder: "asc", page: 2, viewMode: "table" } });
});

describe("passport detail navigation controller", () => {
  it("preserves owner-scoped order and current search context across arrow navigation", async () => {
    const { result } = renderHook(() => usePassportDetailNavigation({ id: ordered[1], group_id: groupId }, query, userId, false));
    await waitFor(() => expect(result.current.navigationIndex).toBe(1));
    expect(result.current.previousHref).toContain(`/passports/${ordered[0]}?`);
    expect(result.current.nextHref).toContain("nav_q=searched");
    act(() => fireEvent.keyDown(window, { key: "ArrowRight" }));
    expect(push).toHaveBeenCalledWith(result.current.nextHref);
  });
  it("ignores arrows during editing and after the listener is disposed", async () => {
    const { result, rerender, unmount } = renderHook(({ editing }) => usePassportDetailNavigation({ id: ordered[1], group_id: groupId }, query, userId, editing), { initialProps: { editing: false } });
    await waitFor(() => expect(result.current.navigationIndex).toBe(1));
    const input = document.createElement("input"); document.body.append(input); input.focus();
    fireEvent.keyDown(input, { key: "ArrowRight", bubbles: true });
    expect(push).not.toHaveBeenCalled(); input.remove();
    rerender({ editing: true }); fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(push).not.toHaveBeenCalled();
    unmount(); fireEvent.keyDown(window, { key: "ArrowRight" }); expect(push).not.toHaveBeenCalled();
  });
  it("rejects stale stored order after account or group changes", async () => {
    const { result, rerender } = renderHook(({ owner, group }) => usePassportDetailNavigation({ id: ordered[1], group_id: group }, query, owner, false), { initialProps: { owner: userId, group: groupId } });
    await waitFor(() => expect(result.current.navigationIndex).toBe(1));
    rerender({ owner: "another-owner", group: groupId });
    expect(result.current.orderedSubmissionIds).toEqual(["server-id"]);
    rerender({ owner: userId, group: "another-group" });
    expect(result.current.activeNavigation).toBeNull();
    expect(result.current.nextHref).toBeNull();
    expect(view.mock.calls.at(-1)?.[2]).toBe(false);
  });
});
