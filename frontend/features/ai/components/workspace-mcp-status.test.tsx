import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkspaceAccessNotice, WorkspaceConnectionIndicator } from "./workspace-mcp-status";

it("only reports workspace connected when MCP confirms access", () => {
  const { rerender } = render(<WorkspaceConnectionIndicator access={null} />);
  expect(screen.getByLabelText("Checking workspace access")).toHaveAttribute("data-connected", "false");
  rerender(<WorkspaceConnectionIndicator access={{ connected: false }} />);
  expect(screen.getByLabelText("Workspace tools unavailable")).toHaveAttribute("data-connected", "false");
  rerender(<WorkspaceConnectionIndicator access={{ connected: true, available_tools: 8 }} />);
  expect(screen.getByLabelText("Workspace connected")).toHaveAttribute("data-connected", "true");
});

it("offers reconnection for no approved connection and selection for ambiguous or stale choices", () => {
  const retry = vi.fn();
  const { rerender } = render(<WorkspaceAccessNotice access={{ connected: false, code: "mcp_connection_unavailable", message: "No approved connection." }} canManage onRetry={retry} />);
  expect(screen.getByRole("status")).toHaveTextContent("No approved connection.");
  expect(screen.getByRole("link", { name: "Reconnect existing MCP connection" })).toHaveAttribute("href", "/admin/mcp/setup");
  for (const code of ["mcp_connection_required", "mcp_access_denied"]) {
    rerender(<WorkspaceAccessNotice access={{ connected: false, code }} canManage onRetry={retry} />);
    expect(screen.getByRole("link", { name: "Choose connection in AI settings" })).toHaveAttribute("href", "/settings/ai#ai-mcp-access");
  }
  rerender(<WorkspaceAccessNotice access={{ connected: false, code: "mcp_connection_unavailable" }} canManage={false} onRetry={retry} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it("retries failed checks and removes the notice after access recovers", async () => {
  const retry = vi.fn();
  const { rerender } = render(<WorkspaceAccessNotice access={{ connected: false, code: "mcp_status_unavailable", message: "Workspace access could not be checked." }} canManage onRetry={retry} />);
  await userEvent.click(screen.getByRole("button", { name: "Check workspace access again" }));
  expect(retry).toHaveBeenCalledOnce();
  rerender(<WorkspaceAccessNotice access={{ connected: true }} canManage onRetry={retry} />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
