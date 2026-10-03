import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { McpPermissionSection } from "../api/mcp.api";
import { McpPermissionSections } from "./mcp-permission-sections";

function section(id: string, label: string, overrides: Partial<McpPermissionSection> = {}): McpPermissionSection {
  return { id, label, read_supported: true, write_supported: true, read_description: "Server read description.",
    write_description: "Server write description.", read_tool_names: [], write_tool_names: [], ...overrides };
}

afterEach(cleanup);

it("shows only supported Read sections and preserves section identifiers when choices change", () => {
  const onChange = vi.fn();
  render(<McpPermissionSections mode="read" disabled={false} selected={["tour_ops"]} onChange={onChange}
    sections={[section("tour_ops", "Tour Ops"), section("codex_access", "MCP administration", { read_supported: false }),
      section("exports", "Exports", { read_supported: false })]} />);
  expect(screen.getByRole("switch", { name: "Read Tour Ops" })).toBeChecked();
  expect(screen.getByText(/passenger QR codes and attendance records/)).toBeVisible();
  expect(screen.queryByText(/MCP administration/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Exports/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("switch", { name: "Read Tour Ops" }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith([]);
});

it("hides unimplemented Write categories while showing the separate broadcast and document workflows", () => {
  render(<McpPermissionSections mode="write" disabled={false} selected={[]} onChange={vi.fn()}
    sections={[section("documents", "Documents", { write_supported: false }),
      section("whatsapp", "WhatsApp", { write_supported: false }),
      section("document_delivery", "Document delivery", { read_supported: false }),
      section("whatsapp_broadcasts", "WhatsApp broadcasts", { read_supported: false })]} />);
  expect(screen.queryByRole("switch", { name: "Write Documents" })).not.toBeInTheDocument();
  expect(screen.queryByRole("switch", { name: "Write WhatsApp" })).not.toBeInTheDocument();
  expect(screen.getByRole("switch", { name: "Write Document delivery" })).toBeEnabled();
  expect(screen.getByRole("switch", { name: "Write WhatsApp broadcasts" })).toBeEnabled();
  expect(screen.getByText(/Sending documents requires final confirmation/)).toBeVisible();
  expect(screen.queryByText(/not available/i)).not.toBeInTheDocument();
});

it("keeps implemented actions visible when turned off globally and prevents device changes", async () => {
  const onChange = vi.fn();
  render(<McpPermissionSections mode="write" disabled={false} selected={["menu"]} onChange={onChange}
    sections={[section("menu", "Menu", { write_allowed_by_settings: false })]} />);
  const control = screen.getByRole("switch", { name: "Write Menu" });
  expect(control).toBeChecked();
  expect(control).toBeDisabled();
  expect(screen.getByText("Off in Settings")).toBeVisible();
  expect(screen.getByText(/Enable this action in Settings/)).toBeVisible();
  await userEvent.click(control);
  expect(onChange).not.toHaveBeenCalled();
});

it("preserves the server description for future configured sections", () => {
  render(<McpPermissionSections mode="write" disabled={false} selected={[]} onChange={vi.fn()}
    sections={[section("future_section", "Future section", { write_description: "Create the configured future record." })]} />);
  expect(screen.getByRole("switch", { name: "Write Future section" })).toBeEnabled();
  expect(screen.getByText("Create the configured future record.")).toBeVisible();
});
