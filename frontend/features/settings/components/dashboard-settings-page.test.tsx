import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useDashboardPreferences } from "../dashboard-preferences";
import { DashboardSettingsPage } from "./dashboard-settings-page";

vi.mock("./platform-settings-panel", () => ({
  PlatformSettingsPanel: () => <div>Platform settings</div>,
}));
vi.mock("@/features/auth/components/account-security-panel", () => ({
  AccountSecurityPanel: () => <div>Account security</div>,
}));

beforeEach(() => {
  useDashboardPreferences.getState().reset();
});

it("applies, persists and resets only real appearance preferences", async () => {
  const user = userEvent.setup();
  render(<DashboardSettingsPage />);
  await user.click(screen.getByRole("button", { name: "Compact" }));
  await user.click(screen.getByRole("button", { name: "Focused" }));
  await user.click(screen.getByRole("switch", { name: "Reduce motion" }));
  await user.click(screen.getByRole("switch", { name: "Compact navigation" }));
  expect(useDashboardPreferences.getState()).toMatchObject({
    density: "compact",
    contentWidth: "focused",
    reduceMotion: true,
    sidebarCollapsed: true,
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
