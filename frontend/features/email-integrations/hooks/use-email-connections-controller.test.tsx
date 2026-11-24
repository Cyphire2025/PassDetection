import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { EmailConnection } from "../types";
import { useEmailConnectionsController } from "./use-email-connections-controller";
import { EmailConnectionsPage } from "../components/connections-page";

const queryData = vi.hoisted(() => ({ connections: [] as EmailConnection[] }));

const mutations = vi.hoisted(() => {
  const mutation = () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false });
  return { authorize: mutation(), sync: mutation(), pause: mutation(),
    resume: mutation(), remove: mutation(), ai: mutation() };
});
vi.mock("./use-email-integrations", () => ({
  useEmailIntegrationStatus: () => ({ data: { enabled: true, providers: [] } }),
  useEmailConnections: () => ({ data: queryData.connections }),
  useEmailIntegrationSummary: () => ({ data: null }),
  useAuthorizeEmailProvider: () => mutations.authorize,
  useSyncEmailConnection: () => mutations.sync,
  usePauseEmailConnection: () => mutations.pause,
  useResumeEmailConnection: () => mutations.resume,
  useRemoveEmailConnection: () => mutations.remove,
  useUpdateEmailAiSettings: () => mutations.ai,
}));

const connection: EmailConnection = {
  id: "mailbox-1", email_address: "owner@example.test", agency_id: "agency-1",
  agency_name: "Synthetic Agency", provider: "gmail", status: "active",
  last_successful_sync_at: null, last_sync_attempt_at: null, last_error_message: null,
  ai_processing_enabled: false, ai_effective_enabled: false, allowed_actions: ["remove", "sync"],
};

beforeEach(() => { vi.clearAllMocks(); queryData.connections = []; });

it("wires the live connection card to a confirmed removal and cleanup notice", () => {
  queryData.connections = [connection];
  render(<EmailConnectionsPage />);
  fireEvent.click(screen.getByRole("button", { name: "Remove account" }));
  const dialog = screen.getByRole("dialog", { name: "Permanently remove email account?" });
  const confirm = within(dialog).getByRole("button", { name: "Permanently remove account" });
  expect(confirm).toBeDisabled();
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: connection.email_address } });
  fireEvent.click(confirm);
  expect(mutations.remove.mutate).toHaveBeenCalledTimes(1);
  act(() => mutations.remove.mutate.mock.calls[0][1].onSuccess({
    storage_cleanup_pending: true, message: "Removed",
  }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText(/Final cleanup of unreferenced stored files/)).toHaveAttribute("role", "status");
});

it("requires the confirmation address and submits one removal until it settles", () => {
  const { result } = renderHook(useEmailConnectionsController);
  act(() => result.current.openRemoval(connection));
  act(() => result.current.confirmRemoval());
  expect(mutations.remove.mutate).not.toHaveBeenCalled();
  act(() => result.current.setRemovalConfirmation("wrong@example.test"));
  act(() => result.current.confirmRemoval());
  expect(mutations.remove.mutate).not.toHaveBeenCalled();
  act(() => result.current.setRemovalConfirmation(" OWNER@example.test "));
  act(() => {
    result.current.confirmRemoval();
    result.current.confirmRemoval();
    result.current.closeRemoval();
  });
  expect(result.current.removeTarget).toEqual(connection);
  expect(mutations.remove.mutate).toHaveBeenCalledExactlyOnceWith(
    { connectionId: "mailbox-1", confirmationEmail: " OWNER@example.test " },
    expect.any(Object),
  );
  act(() => mutations.remove.mutate.mock.calls[0][1].onError());
  act(() => result.current.confirmRemoval());
  expect(mutations.remove.mutate).toHaveBeenCalledTimes(2);
  act(() => mutations.remove.mutate.mock.calls[1][1].onSuccess({
    storage_cleanup_pending: true, message: "Removed",
  }));
  expect(result.current.removeTarget).toBeNull();
  expect(result.current.removalConfirmation).toBe("");
  expect(result.current.notice?.tone).toBe("warning");
});

it("does not overlap account actions and permits retry after failure", () => {
  const { result } = renderHook(useEmailConnectionsController);
  act(() => {
    result.current.runConnectionAction("sync", connection.id);
    result.current.runConnectionAction("pause", connection.id);
    result.current.startAuthorization("gmail");
  });
  expect(mutations.sync.mutate).toHaveBeenCalledTimes(1);
  expect(mutations.pause.mutate).not.toHaveBeenCalled();
  expect(mutations.authorize.mutate).not.toHaveBeenCalled();
  act(() => mutations.sync.mutate.mock.calls[0][1].onError());
  act(() => result.current.runConnectionAction("pause", connection.id));
  act(() => mutations.pause.mutate.mock.calls[0][1].onError());
  expect(result.current.notice?.message).toContain("paused");
  act(() => result.current.runConnectionAction("resume", connection.id));
  act(() => mutations.resume.mutate.mock.calls[0][1].onSuccess());
  expect(result.current.notice?.message).toContain("resumed");
});

it("requires an explicit AI decision and keeps it open during the request", () => {
  const { result } = renderHook(useEmailConnectionsController);
  act(() => result.current.confirmAiSettings());
  expect(mutations.ai.mutate).not.toHaveBeenCalled();
  act(() => result.current.openAiSettings(connection, true));
  act(() => {
    result.current.confirmAiSettings();
    result.current.confirmAiSettings();
    result.current.closeAiSettings();
    result.current.openRemoval(connection);
  });
  expect(mutations.ai.mutate).toHaveBeenCalledTimes(1);
  expect(result.current.aiSettingsTarget).not.toBeNull();
  expect(result.current.removeTarget).toBeNull();
  act(() => mutations.ai.mutate.mock.calls[0][1].onError());
  act(() => result.current.confirmAiSettings());
  act(() => mutations.ai.mutate.mock.calls[1][1].onSuccess({
    enabled: true, effective_enabled: false, message: "Preference saved.",
  }));
  expect(result.current.aiSettingsTarget).toBeNull();
  expect(result.current.notice?.tone).toBe("info");
});

it("rejects unsafe provider redirects and releases the pending action", () => {
  const { result } = renderHook(useEmailConnectionsController);
  act(() => result.current.startAuthorization("outlook"));
  act(() => mutations.authorize.mutate.mock.calls[0][1].onSuccess({
    authorization_url: "https://attacker.example.test/authorize",
  }));
  expect(result.current.notice?.message).toContain("invalid authorization address");
  expect(result.current.activeConnectionId).toBeNull();
  act(() => result.current.startAuthorization("outlook"));
  expect(mutations.authorize.mutate).toHaveBeenCalledTimes(2);
  act(() => mutations.authorize.mutate.mock.calls[1][1].onError());
  expect(result.current.notice?.message).toContain("authorization could not be started");
});
