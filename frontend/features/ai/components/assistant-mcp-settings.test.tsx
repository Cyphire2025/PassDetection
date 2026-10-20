import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { AssistantConfiguration } from "../settings-api";
import { AssistantMcpSettings } from "./assistant-mcp-settings";

const mocks = vi.hoisted(() => ({ mcpAccess: vi.fn() }));
vi.mock("../settings-api", () => ({ aiSettingsApi: mocks }));
const snapshot = { observed_at: "2026-10-21T00:00:00Z", mcp: { connected: true, available_tools: 8, write_enabled: false } };
const configuration: AssistantConfiguration = {
  enabled: true, allowed_roles: [], allowed_user_ids: [], provider: "gemini",
  gemini_model: "gemini-3.8-flash", gemini_live_model: "gemini-3.8-live", gemini_image_model: "gemini-3.1-flash-image",
  gemini_voice: "Zephyr", reasoning_effort: "high", openai_reasoning_effort: "medium", openai_speech_model: "", openai_voice: "marin",
  usage_limits: { daily_voice_chats: 30, voice_connection_minutes: 10, daily_requests: 200, daily_images: 12, daily_uploads: 80, daily_speech_requests: 300 },
  mcp_connection_id: "legacy-revoked-connection", mcp_write_enabled: true,
};
beforeEach(() => { mocks.mcpAccess.mockReset().mockResolvedValue(snapshot); });

it("shows saved session access independently of a legacy external connection and unsaved write preference", async () => {
  const change = vi.fn();
  render(<AssistantMcpSettings value={configuration} onChange={change} />);
  expect(await screen.findByText("8 workspace tools available")).toBeVisible();
  expect(screen.getByText("Saved workspace access")).toBeVisible();
  expect(screen.getByText("Write actions are off for the assistant.")).toBeVisible();
  expect(screen.getByRole("switch", { name: /Allow MCP write access for AI/ })).toBeChecked();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(change).not.toHaveBeenCalled();
});

it("defaults writes off and preserves legacy settings when the user changes only the AI write switch", async () => {
  const change = vi.fn();
  const value = { ...configuration, mcp_write_enabled: undefined };
  render(<AssistantMcpSettings value={value} onChange={change} />);
  await screen.findByText("8 workspace tools available");
  const toggle = screen.getByRole("switch", { name: /Allow MCP write access for AI/ });
  expect(toggle).not.toBeChecked();
  await userEvent.click(toggle);
  expect(change).toHaveBeenCalledExactlyOnceWith({ ...value, mcp_write_enabled: true });
});

it("distinguishes a failed check from denied access and retries without changing saved preferences", async () => {
  mocks.mcpAccess.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(snapshot);
  const change = vi.fn();
  render(<AssistantMcpSettings value={configuration} onChange={change} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be checked");
  expect(screen.queryByText(/Workspace tools are unavailable/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Refresh workspace access" }));
  expect(await screen.findByText("8 workspace tools available")).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("switch", { name: /Allow MCP write access for AI/ })).toBeChecked();
  expect(change).not.toHaveBeenCalled();
});

it.each([
  ["mcp_unavailable", "Workspace MCP access is currently paused or unavailable."],
  ["mcp_access_denied", "Your signed-in account cannot currently use workspace MCP tools. Review your account and AI access settings."],
  ["mcp_no_tools", "Current MCP permissions expose no tools for the assistant. Review workspace permissions and AI settings."],
  ["mcp_ai_disabled", "Enable the AI assistant in settings to use workspace tools."],
])("reports %s without requiring an external connection or changing the user's write choice", async (code, message) => {
  mocks.mcpAccess.mockResolvedValue({ ...snapshot, mcp: { connected: false, code, message } });
  const change = vi.fn();
  render(<AssistantMcpSettings value={configuration} onChange={change} />);
  expect(await screen.findByText(message)).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Refresh workspace access" })).toBeEnabled();
  expect(screen.getByRole("switch", { name: /Allow MCP write access for AI/ })).toBeChecked();
  expect(change).not.toHaveBeenCalled();
});

it("refreshes effective access while keeping the draft unchanged", async () => {
  mocks.mcpAccess.mockResolvedValueOnce(snapshot).mockResolvedValueOnce({ ...snapshot, mcp: { ...snapshot.mcp, write_enabled: true } });
  const change = vi.fn();
  render(<AssistantMcpSettings value={configuration} onChange={change} />);
  await screen.findByText("Write actions are off for the assistant.");
  await userEvent.click(screen.getByRole("button", { name: "Refresh workspace access" }));
  expect(await screen.findByText("Write actions permitted by MCP are available to the assistant.")).toBeVisible();
  expect(change).not.toHaveBeenCalled();
});
