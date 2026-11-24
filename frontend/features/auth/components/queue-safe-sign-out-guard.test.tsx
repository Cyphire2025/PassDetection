import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueueSafeSignOutGuard } from "./queue-safe-sign-out-guard";
import { requestQueueSafeSignOutReview } from "../services/queue-safe-sign-out-events";

const { clear, sync, inspect, authentication } = vi.hoisted(() => ({ clear: vi.fn(), sync: vi.fn(), inspect: vi.fn(), authentication: { user: { id: "synthetic-owner" }, sessionVersion: 1 } }));
vi.mock("@/stores/auth.store", () => ({ useAuthStore: Object.assign(
  (select: (state: unknown) => unknown) => select({ ...authentication, clearSession: clear }),
  { getState: () => ({ ...authentication, clearSession: clear }) },
) }));
vi.mock("@/features/tour-operations/services/attendance-scan-queue", () => ({ syncPendingAttendanceScans: sync, getBrowserAttendanceQueueSafetySnapshot: inspect }));
const snapshot = { ownerUserId: "synthetic-owner", pending: 1, sending: 0, retryable: 0, review: 0, discardAuditPending: 0, oldestQueuedAt: null, nextAttemptAt: null };

describe("queue-safe sign-out focus and destructive intent", () => {
  beforeEach(() => {
    clear.mockReset(); sync.mockReset(); inspect.mockReset(); authentication.user = { id: "synthetic-owner" };
  });
  it("returns to the trigger without deleting queued work when Escape cancels", async () => {
    render(<><button>Sign out</button><QueueSafeSignOutGuard /></>);
    const trigger = screen.getByRole("button", { name: "Sign out" }); trigger.focus();
    act(() => requestQueueSafeSignOutReview(snapshot));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("button", { name: "Keep working" }).at(-1)).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus(); expect(clear).not.toHaveBeenCalled();
  });

  it("retains the keyboard boundary and cannot dismiss while synchronization is pending", async () => {
    let resolve!: () => void;
    sync.mockImplementationOnce(() => new Promise<void>((done) => { resolve = done; }));
    render(<QueueSafeSignOutGuard />); act(() => requestQueueSafeSignOutReview(snapshot));
    await userEvent.click(screen.getByRole("button", { name: "Sync then sign out" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard instead" })).toBeDisabled();
    await act(async () => resolve());
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("could not be synchronized"));
    expect(clear).not.toHaveBeenCalled();
  });

  it("does not discard the replacement account using an old owner's confirmation", async () => {
    render(<QueueSafeSignOutGuard />); act(() => requestQueueSafeSignOutReview(snapshot));
    await userEvent.click(screen.getByRole("button", { name: "Discard instead" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue to final confirmation" }));
    // Keep the old DOM long enough to exercise the handler's own guard rather
    // than relying only on a React subscription/unmount winning the race.
    authentication.user = { id: "replacement-owner" };
    await userEvent.click(screen.getByRole("button", { name: "Permanently discard and sign out" }));
    expect(clear).not.toHaveBeenCalled();
  });

  it("does not inspect or sign out B after A's synchronization finishes", async () => {
    let finish!: () => void;
    sync.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
    inspect.mockResolvedValue({ ...snapshot, ownerUserId: "replacement-owner", pending: 0 });
    render(<QueueSafeSignOutGuard />); act(() => requestQueueSafeSignOutReview(snapshot));
    await userEvent.click(screen.getByRole("button", { name: "Sync then sign out" }));
    authentication.user = { id: "replacement-owner" };
    await act(async () => finish());
    expect(inspect).not.toHaveBeenCalled();
    expect(clear).not.toHaveBeenCalled();
  });
});
