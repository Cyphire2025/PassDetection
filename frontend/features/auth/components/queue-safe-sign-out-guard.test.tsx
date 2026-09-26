import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QueueSafeSignOutGuard } from "./queue-safe-sign-out-guard";
import { requestQueueSafeSignOutReview } from "../services/queue-safe-sign-out-events";

const { clear, sync } = vi.hoisted(() => ({ clear: vi.fn(), sync: vi.fn() }));
vi.mock("@/stores/auth.store", () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ clearSession: clear }) }));
vi.mock("@/features/tour-operations/services/attendance-scan-queue", () => ({ syncPendingAttendanceScans: sync, getBrowserAttendanceQueueSafetySnapshot: vi.fn() }));
const snapshot = { ownerUserId: "synthetic-owner", pending: 1, sending: 0, retryable: 0, review: 0, discardAuditPending: 0, oldestQueuedAt: null, nextAttemptAt: null };

describe("queue-safe sign-out focus and destructive intent", () => {
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
});
