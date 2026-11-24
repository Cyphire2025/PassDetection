import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ClientManagerAccount, ClientManagerSession } from "../types";
import { ClientManagerDetailsDialog } from "./client-manager-details-dialog";

const mocks = vi.hoisted(() => ({ setStatus: vi.fn(), reset: vi.fn(), copy: vi.fn(), sessions: [] as ClientManagerSession[] }));
vi.mock("@/lib/utils/clipboard", () => ({ copyTextToClipboard: mocks.copy }));
vi.mock("../hooks/use-gc-app-admin", () => ({
  useClientManagerMutations: () => ({
    setStatus: { mutateAsync: mocks.setStatus, isPending: false }, resetPassword: { mutateAsync: mocks.reset, isPending: false },
    revokeSessions: { mutateAsync: vi.fn(), isPending: false }, softDelete: { mutateAsync: vi.fn(), isPending: false },
  }),
  useClientManagerSessions: () => ({ data: { items: mocks.sessions, total: 0 } }),
  useClientManagerAudit: () => ({ data: { items: [], total: 0 } }),
}));
const original: ClientManagerAccount = { id: "manager", name: "Synthetic Manager", email: "synthetic@example.test", phone_number: "000",
  company: { id: "company", name: "Synthetic Company" }, assigned_groups: [], status: "active", revision: 4,
  last_login_at: null, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };
function Details() {
  const [manager, setManager] = useState(original);
  return <ClientManagerDetailsDialog open agencyId="agency" manager={manager} onUpdated={setManager} onClose={vi.fn()} onEdit={vi.fn()} />;
}
beforeEach(() => { vi.resetAllMocks(); mocks.sessions = []; });
afterEach(cleanup);

it("offers roving keyboard tabs linked to the visible account panel", () => {
  render(<Details />);
  const overview = screen.getByRole("tab", { name: "overview" });
  const sessions = screen.getByRole("tab", { name: "sessions" });
  expect(overview).toHaveAttribute("tabindex", "0");
  expect(sessions).toHaveAttribute("tabindex", "-1");
  overview.focus();
  fireEvent.keyDown(overview, { key: "ArrowRight" });
  expect(sessions).toHaveFocus();
  expect(sessions).toHaveAttribute("aria-selected", "true");
  const panel = screen.getByRole("tabpanel");
  expect(sessions).toHaveAttribute("aria-controls", panel.id);
  expect(panel).toHaveAttribute("aria-labelledby", sessions.id);
  fireEvent.keyDown(sessions, { key: "End" });
  expect(screen.getByRole("tab", { name: "audit" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("tab", { name: "audit" }), { key: "Home" });
  expect(overview).toHaveFocus();
});

it("adopts the server status and revision before the next security action", async () => {
  mocks.setStatus.mockResolvedValueOnce({ ...original, status: "suspended", revision: 5 }).mockResolvedValueOnce({ ...original, revision: 6 });
  render(<Details />);
  fireEvent.click(screen.getByRole("button", { name: "Suspend account" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  fireEvent.click(await screen.findByRole("button", { name: "Reactivate account" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(mocks.setStatus).toHaveBeenCalledTimes(2));
  expect(mocks.setStatus.mock.calls[1]?.[0]).toMatchObject({ revision: 5, status: "active" });
});

it("admits a security confirmation only once before mutation state rerenders", async () => {
  let finish!: (result: ClientManagerAccount) => void;
  mocks.setStatus.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  render(<Details />);
  fireEvent.click(screen.getByRole("button", { name: "Suspend account" }));
  const confirm = screen.getByRole("button", { name: "Confirm" });
  act(() => { fireEvent.click(confirm); fireEvent.click(confirm); });
  expect(mocks.setStatus).toHaveBeenCalledOnce();
  await act(async () => { finish({ ...original, status: "suspended", revision: 5 }); });
});

it("keeps the one-time activation link available when copying fails", async () => {
  mocks.reset.mockResolvedValue({ ...original, revision: 5, activation_token: "synthetic-one-time-token" });
  mocks.copy.mockRejectedValue(new Error("Synthetic clipboard denied"));
  render(<Details />);
  fireEvent.click(screen.getByRole("button", { name: "Issue reset link" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Issue reset link" })[1]!);
  fireEvent.click(await screen.findByRole("button", { name: "Copy link" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be copied");
  expect(screen.getByText(/synthetic-one-time-token/)).toBeInTheDocument();
});

it("distinguishes expired and active sessions without claiming the manager's device is current", () => {
  const session = { id: "expired", device_name: null, platform: "test", app_version: null, ip_address: null, created_at: original.created_at,
    last_seen_at: null, revoked_at: null, current: true, status: "active", expires_at: "2000-01-01T00:00:00Z" };
  mocks.sessions = [session, { ...session, id: "active", expires_at: "2100-01-01T00:00:00Z" }];
  render(<Details />);
  fireEvent.click(screen.getByRole("tab", { name: "sessions" }));
  expect(screen.getByText("Expired")).toBeInTheDocument();
  expect(screen.getByText("Active")).toBeInTheDocument();
  expect(screen.queryByText("Current")).not.toBeInTheDocument();
});
