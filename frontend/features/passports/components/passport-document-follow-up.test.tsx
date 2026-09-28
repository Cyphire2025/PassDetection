import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { useState, type ComponentProps, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QUERY_KEYS } from "@/constants";
import apiClient from "@/lib/api/client";
import { passportsApi, type PassportGroupSubmissionsView } from "../api/passports.api";
import { parsePassportGroupViewState } from "../utils/passport-group-navigation";
import { DocumentFollowUpActions, DocumentFollowUpBadge } from "./passport-document-follow-up";
import { PassportGroupSelectionToolbar } from "./passport-group-selection-toolbar";
import { usePassportDocumentFollowUp } from "./use-passport-document-follow-up";

afterEach(() => vi.restoreAllMocks());

function setupQueryClient() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

function followUpOptions() {
  return {
    groupId: "group-1", selectedPassports: ["visible", "other-page"], canManage: true,
    flaggedCount: 2, viewStatus: { isLoading: false, isFetching: false }, includeDeleted: false, groupStatus: "active", submissionFilter: "all" as const,
    setSubmissionFilter: vi.fn(), setPage: vi.fn(), closeMenu: vi.fn(), setFeedback: vi.fn(),
  };
}

function toolbarProps(count?: number) {
  return {
    search: "different person", setSearch: vi.fn(), setPage: vi.fn(), isFetching: false,
    isLoading: false, sortBy: "name", setSortBy: vi.fn(), submissionFilter: "all",
    setSubmissionFilter: vi.fn(), sortOrder: "asc", setSortOrder: vi.fn(), selectionPreset: "",
    handleSelectionPreset: vi.fn(), selectedPassports: [], isBulkActionsMenuOpen: false,
    viewMode: "table", setViewMode: vi.fn(),
    submissionsView: { items: [], total: 0, document_follow_up_count: count } as unknown as PassportGroupSubmissionsView,
  } as unknown as ComponentProps<typeof PassportGroupSelectionToolbar>;
}

describe("document follow-up filter", () => {
  it("appears from the group-wide count even when search hides every flagged person", () => {
    const props = toolbarProps(0);
    const { rerender } = render(<PassportGroupSelectionToolbar {...props} />);
    expect(screen.queryByRole("option", { name: "Flagged for follow-up" })).not.toBeInTheDocument();
    rerender(<PassportGroupSelectionToolbar {...props} submissionsView={toolbarProps(2).submissionsView} />);
    expect(screen.getByRole("option", { name: "Flagged for follow-up" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter submissions"), { target: { value: "document_follow_up" } });
    expect(props.setSubmissionFilter).toHaveBeenCalledWith("document_follow_up");
    expect(props.setPage).toHaveBeenCalledWith(1);
    rerender(<PassportGroupSelectionToolbar {...props} />);
    expect(screen.queryByRole("option", { name: "Flagged for follow-up" })).not.toBeInTheDocument();
  });

  it("waits for a settled group count before resetting the last-cleared flagged filter", async () => {
    const { wrapper } = setupQueryClient();
    const options = { ...followUpOptions(), submissionFilter: "document_follow_up" as const };
    const { rerender } = renderHook(({ ready, count }) => usePassportDocumentFollowUp({
      ...options, viewStatus: { isLoading: false, isFetching: !ready }, flaggedCount: count,
    }), { wrapper, initialProps: { ready: false, count: undefined as number | undefined } });
    expect(options.setSubmissionFilter).not.toHaveBeenCalled();
    rerender({ ready: false, count: 0 });
    expect(options.setSubmissionFilter).not.toHaveBeenCalled();
    rerender({ ready: true, count: 1 });
    expect(options.setSubmissionFilter).not.toHaveBeenCalled();
    rerender({ ready: true, count: 0 });
    await waitFor(() => expect(options.setSubmissionFilter).toHaveBeenCalledWith("all"));
    expect(options.setPage).toHaveBeenCalledWith(1);
  });

  it("retains the flag filter in group and detail navigation URLs", () => {
    expect(parsePassportGroupViewState(new URLSearchParams("filter=document_follow_up")).submissionFilter)
      .toBe("document_follow_up");
    expect(parsePassportGroupViewState(new URLSearchParams("group_filter=document_follow_up"), "group_").submissionFilter)
      .toBe("document_follow_up");
  });

  it.each([
    { isLoading: true, isFetching: false },
    { isLoading: false, isFetching: false, isPlaceholderData: true },
    { isLoading: false, isFetching: false, error: new Error("Reload failed") },
  ])("does not reset the filter for an incomplete or failed response: %j", async (viewStatus) => {
    const { wrapper } = setupQueryClient();
    const options = { ...followUpOptions(), flaggedCount: 0, submissionFilter: "document_follow_up" as const, viewStatus };
    renderHook(() => usePassportDocumentFollowUp(options), { wrapper });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    expect(options.setSubmissionFilter).not.toHaveBeenCalled();
  });
});

describe("document follow-up actions", () => {
  it.each([true, false])("persists flagged=%s for the whole selection and refreshes passport data", async (flagged) => {
    const { client, wrapper } = setupQueryClient();
    const queryKey = QUERY_KEYS.passports.groupDetail("group-1", { page: 1 });
    client.setQueryData(queryKey, { marker: "cached roster" });
    const api = vi.spyOn(passportsApi, "bulkDocumentFollowUp").mockResolvedValue({ updated_count: 2, flagged });
    const options = followUpOptions();
    const { result } = renderHook(() => usePassportDocumentFollowUp(options), { wrapper });
    act(() => result.current.update(flagged));
    await waitFor(() => expect(options.setFeedback).toHaveBeenLastCalledWith({
      tone: "success", message: flagged ? "2 people flagged for document follow-up." : "Document follow-up flag cleared for 2 people.",
    }));
    expect(api).toHaveBeenCalledWith("group-1", { submission_ids: ["visible", "other-page"], flagged });
    expect(client.getQueryState(queryKey)?.isInvalidated).toBe(true);
    expect(options.closeMenu).toHaveBeenCalledOnce();
    expect(options.setPage).not.toHaveBeenCalled();
    expect(options.selectedPassports).toEqual(["visible", "other-page"]);
  });

  it("reports save errors, keeps the selection, and permits retry", async () => {
    const { wrapper } = setupQueryClient();
    const api = vi.spyOn(passportsApi, "bulkDocumentFollowUp").mockRejectedValueOnce(new Error("Server unavailable"))
      .mockResolvedValueOnce({ updated_count: 2, flagged: true });
    const options = followUpOptions();
    const { result } = renderHook(() => usePassportDocumentFollowUp(options), { wrapper });
    act(() => result.current.update(true));
    await waitFor(() => expect(options.setFeedback).toHaveBeenLastCalledWith({ tone: "error", message: "Server unavailable" }));
    expect(options.selectedPassports).toEqual(["visible", "other-page"]);
    act(() => result.current.update(true));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
  });

  it("blocks repeated clicks while saving and disables both menu choices", async () => {
    const { wrapper } = setupQueryClient();
    let finish!: (result: { updated_count: number; flagged: boolean }) => void;
    const api = vi.spyOn(passportsApi, "bulkDocumentFollowUp").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    function Harness() {
      const [options] = useState(followUpOptions);
      const followUp = usePassportDocumentFollowUp(options);
      return <DocumentFollowUpActions followUp={followUp} selectedCount={2} />;
    }
    render(<Harness />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: "Flag for document follow-up (2)" }));
    fireEvent.click(screen.getByRole("button", { name: "Flag for document follow-up (2)" }));
    await waitFor(() => expect(api).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Flag for document follow-up (2)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear document follow-up flag (2)" })).toBeDisabled();
    await act(async () => finish({ updated_count: 2, flagged: true }));
  });

  it("hides actions and refuses requests without management permission", () => {
    const { wrapper } = setupQueryClient();
    const api = vi.spyOn(passportsApi, "bulkDocumentFollowUp");
    const options = { ...followUpOptions(), canManage: false };
    const { result } = renderHook(() => usePassportDocumentFollowUp(options), { wrapper });
    render(<DocumentFollowUpActions followUp={result.current} selectedCount={2} />);
    expect(screen.queryByRole("button", { name: /document follow-up/ })).not.toBeInTheDocument();
    act(() => result.current.update(true));
    expect(api).not.toHaveBeenCalled();
  });

  it.each([{ includeDeleted: true }, { groupStatus: "archived" }])("hides actions for a historical group: %j", (history) => {
    const { wrapper } = setupQueryClient();
    const api = vi.spyOn(passportsApi, "bulkDocumentFollowUp");
    const { result } = renderHook(() => usePassportDocumentFollowUp({ ...followUpOptions(), ...history }), { wrapper });
    expect(result.current.canManage).toBe(false);
    act(() => result.current.update(true));
    expect(api).not.toHaveBeenCalled();
  });

  it("sends the agreed scoped endpoint and request body", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { updated_count: 1, flagged: true } });
    await passportsApi.bulkDocumentFollowUp("group-123", { submission_ids: ["person-123"], flagged: true });
    expect(post).toHaveBeenCalledWith("/api/v1/passports/groups/group-123/bulk-document-follow-up", {
      submission_ids: ["person-123"], flagged: true,
    });
  });

  it("shows a separate follow-up badge only for flagged records", () => {
    const { rerender } = render(<DocumentFollowUpBadge />);
    expect(screen.queryByText("Document follow-up")).not.toBeInTheDocument();
    rerender(<DocumentFollowUpBadge flagged />);
    expect(screen.getByText("Document follow-up")).toBeInTheDocument();
  });
});
