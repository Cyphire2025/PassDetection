import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { EmailAiRolloutTarget } from "../types";
import { EmailAiRolloutControl } from "./email-ai-rollout-control";

const fixture = vi.hoisted(() => ({
  targets: [] as EmailAiRolloutTarget[],
  queries: vi.fn(),
  mutation: { mutate: vi.fn(), reset: vi.fn(), isPending: false },
}));
vi.mock("../hooks/use-email-integrations", () => ({
  useEmailAiRolloutTargets: (...args: unknown[]) => {
    fixture.queries(...args);
    return { data: { items: fixture.targets, global_enabled: true, global_notifications_enabled: true } };
  },
  useUpdateEmailAiRolloutPolicy: () => fixture.mutation,
}));
const admin: User = {
  id: "rollout-admin", email: "admin@example.test", full_name: "Synthetic Admin",
  role: "super_admin", agency_id: null, is_active: true,
  last_login_at: null, created_at: "2026-10-30", updated_at: "2026-10-30",
};
const target: EmailAiRolloutTarget = {
  scope_type: "agency", target_id: "agency-1", agency_id: "agency-1",
  owner_user_id: null, connection_id: null, label: "Synthetic Agency", detail: null,
  direct_enabled: true, effective_enabled: true, updated_at: "2026-10-30T10:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  fixture.targets = [target];
  useAuthStore.setState({ user: admin });
});

it("hides rollout controls and disables their query for non-super-admins", () => {
  useAuthStore.setState({ user: { ...admin, role: "agency_admin", agency_id: "agency-1" } });
  render(<EmailAiRolloutControl />);
  expect(screen.queryByRole("heading", { name: "AI rollout controls" })).not.toBeInTheDocument();
  expect(fixture.queries).toHaveBeenCalledWith(admin.id, "agency", "", false);
  expect(fixture.mutation.mutate).not.toHaveBeenCalled();
});

it("submits the version explicitly confirmed before a background refresh", () => {
  const { rerender } = render(<EmailAiRolloutControl />);
  fireEvent.click(screen.getByRole("button", { name: "Pause" }));
  const dialog = screen.getByRole("dialog", { name: "Pause AI for Synthetic Agency?" });
  fixture.targets = [{ ...target, updated_at: "2026-10-30T11:00:00Z" }];
  rerender(<EmailAiRolloutControl />);
  fireEvent.click(within(dialog).getByRole("button", { name: "Pause" }));
  expect(fixture.mutation.mutate).toHaveBeenCalledExactlyOnceWith({
    scope_type: "agency", target_id: "agency-1", agency_id: "agency-1",
    enabled: false, expected_updated_at: target.updated_at,
  }, expect.any(Object));
  act(() => fixture.mutation.mutate.mock.calls[0][1].onSuccess({ ...target, direct_enabled: false }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText("Synthetic Agency is paused at this level.")).toHaveAttribute("role", "status");
});

it("closes stale decisions and asks for fresh review after a conflict", () => {
  render(<EmailAiRolloutControl />);
  fireEvent.click(screen.getByRole("button", { name: "Pause" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Pause" }));
  act(() => fixture.mutation.mutate.mock.calls[0][1].onError({ code: "HTTP_409" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText(/latest settings are being refreshed/)).toHaveAttribute("role", "status");
});
