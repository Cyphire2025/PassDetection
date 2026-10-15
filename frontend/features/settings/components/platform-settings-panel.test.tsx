import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { DEFAULT_PLATFORM_SETTINGS } from "../platform-settings-policy";
import { PlatformSettingsPanel } from "./platform-settings-panel";

const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: client }));
const admin: User = {
  id: "policy-admin", email: "policy@example.test", full_name: "Policy Admin",
  role: "agency_admin", agency_id: "policy-agency", is_active: true,
  last_login_at: null, created_at: "2026-10-06", updated_at: "2026-10-06",
};
const saved = { ...DEFAULT_PLATFORM_SETTINGS, updated_at: "2026-10-06T12:00:00Z" };

beforeEach(() => {
  vi.clearAllMocks();
  client.get.mockResolvedValue({ data: saved });
  client.put.mockResolvedValue({ data: saved });
  useAuthStore.setState({ user: admin });
});

it("lets agency administrators read platform policies without editing or saving them", async () => {
  render(<PlatformSettingsPanel section="policies" />);
  expect(await screen.findByLabelText("Platform name")).toHaveValue(saved.platform_name);
  expect(screen.getByLabelText("Platform name")).toBeDisabled();
  const save = screen.getByRole("button", { name: "Save policies" });
  expect(save).toBeDisabled();
  expect(screen.getByText(/Only a super administrator/)).toBeVisible();
  fireEvent.click(save);
  expect(client.put).not.toHaveBeenCalled();
});

it("allows super-admin policy saves and immediately removes editing after a role change", async () => {
  useAuthStore.setState({ user: { ...admin, role: "super_admin", agency_id: null } });
  render(<PlatformSettingsPanel section="policies" />);
  const name = await screen.findByLabelText("Platform name");
  expect(name).toBeEnabled();
  fireEvent.change(name, { target: { value: "Updated platform" } });
  fireEvent.click(screen.getByRole("button", { name: "Save policies" }));
  await waitFor(() => expect(client.put).toHaveBeenCalledWith(
    "/api/v1/admin/settings", expect.objectContaining({ platform_name: "Updated platform" }),
  ));
  await screen.findByText("Settings saved.");
  act(() => useAuthStore.setState({ user: admin }));
  expect(name).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save policies" })).toBeDisabled();
});
