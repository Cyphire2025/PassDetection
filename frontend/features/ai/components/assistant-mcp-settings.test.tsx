import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { AssistantConfiguration } from "../settings-api";
import { AssistantMcpSettings } from "./assistant-mcp-settings";

const mocks = vi.hoisted(() => ({ mcpConnections: vi.fn() }));
vi.mock("../settings-api", () => ({ aiSettingsApi: mocks }));
const connection = { id: "existing-a", name: "Existing desktop", read_enabled: true, write_enabled: true };
const configuration: AssistantConfiguration = {
  enabled: true, allowed_roles: [], allowed_user_ids: [], provider: "gemini",
  gemini_model: "gemini-3.8-flash", gemini_live_model: "gemini-3.8-live", gemini_image_model: "gemini-3.1-flash-image",
  gemini_voice: "Zephyr", reasoning_effort: "high", openai_reasoning_effort: "medium", openai_speech_model: "", openai_voice: "marin",
  usage_limits: { daily_voice_chats: 30, voice_connection_minutes: 10, daily_requests: 200, daily_images: 12, daily_uploads: 80, daily_speech_requests: 300 },
  mcp_connection_id: null, mcp_write_enabled: true,
};
beforeEach(() => { mocks.mcpConnections.mockReset().mockResolvedValue({ items: [] }); });

it("explains zero authorized connections without changing the saved AI write preference", async () => {
  const change = vi.fn();
  render(<AssistantMcpSettings value={configuration} onChange={change} />);
  expect(await screen.findByText(/No active authorized MCP connection is available/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Reconnect existing MCP connection" })).toHaveAttribute("href", "/admin/mcp/setup");
  expect(screen.getByRole("combobox", { name: "MCP connection" })).toBeDisabled();
  expect(screen.getByRole("switch", { name: /Allow MCP write access for AI/ })).toBeChecked();
  expect(change).not.toHaveBeenCalled();
});

it("distinguishes load failure from no connections and retries without clearing the saved selection", async () => {
  mocks.mcpConnections.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ items: [connection] });
  const change = vi.fn();
  render(<AssistantMcpSettings value={{ ...configuration, mcp_connection_id: connection.id }} onChange={change} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
  expect(screen.queryByText(/No active authorized MCP connection/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Reconnect existing MCP connection" })).not.toBeInTheDocument();
  const select = screen.getByRole("combobox", { name: "MCP connection" });
  expect(select).toHaveValue(connection.id);
  await userEvent.click(screen.getByRole("button", { name: "Refresh connections" }));
  await waitFor(() => expect(select).toBeEnabled());
  expect(select).toHaveValue(connection.id);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(change).not.toHaveBeenCalled();
});

it("requires an explicit choice among multiple connections without silently choosing one", async () => {
  mocks.mcpConnections.mockResolvedValue({ items: [connection, { ...connection, id: "existing-b", name: "Other desktop" }] });
  const change = vi.fn();
  render(<AssistantMcpSettings value={configuration} onChange={change} />);
  await screen.findByText(/More than one connection is available/);
  const select = screen.getByRole("combobox", { name: "MCP connection" });
  expect(select).toHaveValue("");
  expect(change).not.toHaveBeenCalled();
  await userEvent.selectOptions(select, "existing-b");
  expect(change).toHaveBeenCalledWith({ ...configuration, mcp_connection_id: "existing-b" });
});

it("explains automatic selection only when exactly one connection is available", async () => {
  mocks.mcpConnections.mockResolvedValue({ items: [connection] });
  const change = vi.fn();
  render(<AssistantMcpSettings value={configuration} onChange={change} />);
  await screen.findByText("Using your only available connection automatically.");
  expect(screen.getByRole("combobox", { name: "MCP connection" })).toHaveValue("");
  expect(change).not.toHaveBeenCalled();
});

it("preserves a stale selection and accurately labels disabled read access", async () => {
  mocks.mcpConnections.mockResolvedValue({ items: [{ ...connection, read_enabled: false, write_enabled: false }] });
  const change = vi.fn();
  render(<AssistantMcpSettings value={{ ...configuration, mcp_connection_id: "revoked" }} onChange={change} />);
  await screen.findByText(/The saved connection is unavailable/);
  expect(screen.getByRole("combobox", { name: "MCP connection" })).toHaveValue("revoked");
  expect(screen.getByRole("option", { name: "Existing desktop · data access disabled" })).toBeInTheDocument();
  expect(change).not.toHaveBeenCalled();
});
