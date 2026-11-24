import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { UploadLinkResponse } from "../api/upload-links.api";
import { UploadLinkList } from "./upload-link-list";

const fixture = vi.hoisted(() => ({
  active: { data: undefined as UploadLinkResponse[] | undefined, isLoading: false, isFetching: false, error: null as Error | null, refetch: vi.fn() },
  archived: { data: undefined as UploadLinkResponse[] | undefined, isLoading: false, isFetching: false, error: null as Error | null, refetch: vi.fn() },
  copy: vi.fn(),
}));
vi.mock("../hooks/use-upload-links", () => {
  const mutation = () => ({ mutate: vi.fn(), isPending: false, reset: vi.fn() });
  return { useUploadLinks: (status?: string) => status === "archived" ? fixture.archived : fixture.active,
    useDeleteUploadLink: mutation, usePermanentlyDeleteUploadLink: mutation, useRestoreUploadLink: mutation, useRevokeUploadLink: mutation };
});
vi.mock("@/lib/utils/clipboard", () => ({ copyTextToClipboard: fixture.copy }));
vi.mock("./edit-group-dialog", () => ({ EditGroupDialog: () => null }));

const group = { id: "synthetic", name: "Synthetic group", token: "synthetic-token", status: "active", departure_cities: [], created_at: "2026-01-01", travel_date: null } as unknown as UploadLinkResponse;
beforeEach(() => {
  for (const query of [fixture.active, fixture.archived]) Object.assign(query, { data: [], isLoading: false, isFetching: false, error: null, refetch: vi.fn() });
  fixture.copy.mockReset().mockResolvedValue(undefined);
  useAuthStore.setState({ user: { id: "reviewer", role: "agency_admin", agency_id: "agency" } as User });
});
afterEach(() => vi.useRealTimers());

describe("Group Links load and refresh states", () => {
  it("shows unavailable active totals and explicit retry after initial failure", () => {
    fixture.active.data = undefined;
    fixture.active.error = new Error("Synthetic unavailable");
    render(<UploadLinkList />);
    expect(screen.queryByRole("heading", { name: "No Group Links are collecting details" })).not.toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Group Link lifecycle summary" });
    expect(within(summary).getAllByText("Unavailable")).toHaveLength(3);
    expect(screen.getByRole("alert")).toHaveTextContent("Live and closed Group Links could not be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Retry live and closed links" }));
    expect(fixture.active.refetch).toHaveBeenCalledOnce();
    expect(fixture.archived.refetch).not.toHaveBeenCalled();
  });

  it("shows archived failure independently and never reports missing history as empty", () => {
    fixture.active.data = [group];
    fixture.archived.data = undefined;
    fixture.archived.error = new Error("Synthetic archive unavailable");
    render(<UploadLinkList />);
    fireEvent.click(screen.getByRole("button", { name: "Show archived groups" }));
    expect(screen.queryByRole("heading", { name: "No archived Group Links" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Archived Group Links could not be loaded");
    expect(screen.getAllByText("Synthetic group")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Retry archived links" }));
    expect(fixture.archived.refetch).toHaveBeenCalledOnce();
  });

  it("labels saved rows after a refresh error and disables duplicate retry while fetching", () => {
    fixture.active.data = [group];
    fixture.active.error = new Error("Synthetic refresh failure");
    fixture.active.isFetching = true;
    render(<UploadLinkList />);
    expect(screen.getByRole("alert")).toHaveTextContent("Previously loaded links remain visible");
    expect(screen.getAllByText("Synthetic group")).toHaveLength(2);
    const retry = screen.getByRole("button", { name: "Retry live and closed links" });
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(fixture.active.refetch).not.toHaveBeenCalled();
  });

  it("keeps a successful empty response distinct from unavailable data", () => {
    render(<UploadLinkList />);
    expect(screen.getByRole("heading", { name: "No Group Links are collecting details" })).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Group Link lifecycle summary" });
    expect(within(summary).getAllByText("0")).toHaveLength(4);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("Group Link copy feedback lifetime", () => {
  it("keeps repeat-copy confirmation visible for two seconds from the latest copy", async () => {
    vi.useFakeTimers(); fixture.active.data = [group];
    render(<UploadLinkList />);
    const copy = screen.getAllByRole("button", { name: /^Copy .*upload link/ })[0];
    await act(async () => fireEvent.click(copy));
    await act(() => vi.advanceTimersByTimeAsync(1_500));
    await act(async () => fireEvent.click(copy));
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(copy).toHaveTextContent("Copied");
    await act(() => vi.advanceTimersByTimeAsync(1_500));
    expect(copy).not.toHaveTextContent("Copied");
  });

  it("does not create a feedback timer when an abandoned clipboard operation resolves", async () => {
    vi.useFakeTimers(); fixture.active.data = [group];
    let finish!: () => void;
    fixture.copy.mockReturnValueOnce(new Promise<void>((resolve) => { finish = resolve; }));
    const { unmount } = render(<UploadLinkList />);
    fireEvent.click(screen.getAllByRole("button", { name: /^Copy .*upload link/ })[0]);
    unmount();
    await act(async () => finish());
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ignores an older clipboard failure after a newer copy succeeds", async () => {
    fixture.active.data = [group];
    let fail!: (reason: Error) => void;
    fixture.copy.mockReturnValueOnce(new Promise<void>((_, reject) => { fail = reject; }));
    render(<UploadLinkList />);
    const copy = screen.getAllByRole("button", { name: /^Copy .*upload link/ })[0];
    fireEvent.click(copy);
    await act(async () => fireEvent.click(copy));
    await act(async () => fail(new Error("Old clipboard request denied")));
    expect(copy).toHaveTextContent("Copied");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
