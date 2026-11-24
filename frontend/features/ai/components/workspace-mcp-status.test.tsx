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

it("guides managers to AI access settings for current policy restrictions without external reconnection", () => {
  const retry = vi.fn();
  const { rerender } = render(<WorkspaceAccessNotice access={{ connected: false, code: "mcp_no_tools", message: "No tools permitted." }} canManage onRetry={retry} />);
  expect(screen.getByRole("status")).toHaveTextContent("No tools permitted.");
  for (const code of ["mcp_no_tools", "mcp_access_denied", "mcp_ai_disabled"]) {
    rerender(<WorkspaceAccessNotice access={{ connected: false, code }} canManage onRetry={retry} />);
    expect(screen.getByRole("link", { name: "Review AI workspace access" })).toHaveAttribute("href", "/settings/ai#ai-mcp-access");
  }
  rerender(<WorkspaceAccessNotice access={{ connected: false, code: "mcp_access_denied" }} canManage={false} onRetry={retry} />);
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
