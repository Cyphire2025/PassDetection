import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useDashboardPreferences } from "../dashboard-preferences";
import { DashboardSettingsPage } from "./dashboard-settings-page";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types/auth.types";

vi.mock("./platform-settings-panel", () => ({
  PlatformSettingsPanel: ({ section }: { section: string }) => <label>Platform {section}<input aria-label="Policy draft" defaultValue="" /></label>,
}));
vi.mock("./whatsapp-template-settings-panel", () => ({
  WhatsAppTemplateSettingsPanel: ({ active }: { active: boolean }) => <input aria-label="Template draft" data-active={active} defaultValue="" />,
}));

const admin: User = {
  id: "admin-a", email: "admin@example.test", full_name: "Test Admin", role: "agency_admin",
  agency_id: "agency-a", is_active: true, last_login_at: null, created_at: "2026-09-26", updated_at: "2026-09-26",
};
vi.mock("@/features/auth/components/account-security-panel", () => ({
  AccountSecurityPanel: () => <div>Account security</div>,
}));

beforeEach(() => {
  useDashboardPreferences.getState().reset();
  useAuthStore.setState({ user: null });
});

it("applies, persists and resets only real appearance preferences", async () => {
  const user = userEvent.setup();
  render(<DashboardSettingsPage />);
  await user.click(screen.getByRole("button", { name: "Compact" }));
  await user.click(screen.getByRole("button", { name: "Focused" }));
  await user.click(screen.getByRole("button", { name: "Larger" }));
  await user.click(screen.getByRole("switch", { name: "Reduce motion" }));
  await user.click(screen.getByRole("switch", { name: "Compact navigation" }));
  expect(useDashboardPreferences.getState()).toMatchObject({
    density: "compact",
    contentWidth: "focused",
    reduceMotion: true,
    sidebarCollapsed: true,
    textSize: "large",
  });
  const saved = JSON.parse(
    localStorage.getItem("passdetection-dashboard-preferences") ?? "{}",
  );
  expect(saved.state).toMatchObject({
    density: "compact",
    contentWidth: "focused",
    reduceMotion: true,
  });
  expect(Object.keys(saved.state)).toHaveLength(5);
  await user.click(screen.getByRole("button", { name: "Reset appearance" }));
  expect(useDashboardPreferences.getState()).toMatchObject({
    density: "comfortable",
    contentWidth: "wide",
    reduceMotion: false,
    sidebarCollapsed: false,
  });
});

it("preserves policy drafts across sections and exposes only permitted template navigation", async () => {
  const user = userEvent.setup();
  render(<DashboardSettingsPage />);
  expect(screen.queryByRole("button", { name: /WhatsApp templates/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Platform policies/ }));
  await user.type(screen.getByRole("textbox", { name: "Policy draft" }), "Pending policy");
  await user.click(screen.getByRole("button", { name: /Account & security/ }));
  expect(screen.getByText("Account security")).toBeVisible();
  expect(screen.getAllByText("Unavailable")).toHaveLength(3);
  await user.click(screen.getByRole("button", { name: /Data administration/ }));
  expect(screen.getByText("Platform data")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Policy draft" })).toHaveValue("Pending policy");
});

it("loads templates only on demand, preserves their draft when hidden and clears it when identity changes", async () => {
  useAuthStore.setState({ user: admin });
  const user = userEvent.setup();
  render(<DashboardSettingsPage />);
  expect(screen.queryByLabelText("Template draft")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /WhatsApp templates/ }));
  await user.type(await screen.findByRole("textbox", { name: "Template draft" }), "Pending template");
  await user.click(screen.getByRole("button", { name: /Account & security/ }));
  expect(screen.getByText("Test Admin")).toBeVisible();
  expect(screen.getByText("agency admin")).toBeVisible();
  expect(screen.getByLabelText("Template draft")).not.toBeVisible();
  await user.click(screen.getByRole("button", { name: /WhatsApp templates/ }));
  expect(screen.getByRole("textbox", { name: "Template draft" })).toHaveValue("Pending template");
  act(() => useAuthStore.setState({ user: { ...admin, id: "admin-b" } }));
  expect(screen.getByRole("textbox", { name: "Template draft" })).toHaveValue("");
  act(() => useAuthStore.setState({ user: { ...admin, role: "agency_staff" } }));
  expect(screen.queryByLabelText("Template draft")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /WhatsApp templates/ })).not.toBeInTheDocument();
});
