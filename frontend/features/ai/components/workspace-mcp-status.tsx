import Link from "next/link";
import type { McpAccessStatus } from "../types";
import styles from "./workspace.module.css";

export function WorkspaceConnectionIndicator({ access }: { access: McpAccessStatus | null }) {
  const label = access?.connected ? "Workspace connected" : access ? "Workspace tools unavailable" : "Checking workspace access";
  return <span className={styles.connectionDot} data-connected={access?.connected === true} aria-label={label} title={access?.message || label} />;
}

export function WorkspaceAccessNotice({ access, canManage, onRetry }: {
  access: McpAccessStatus | null; canManage: boolean; onRetry: () => void;
}) {
  if (!access || access.connected) return null;
  const retry = access.code === "mcp_status_unavailable" || access.code === "mcp_unavailable";
  const reconnect = access.code === "mcp_connection_unavailable";
  return <div className={styles.workspaceNotice} role="status">
    <p>{access.message || "Workspace tools are unavailable. You can still chat and use your own attachments."}</p>
    {retry ? <button type="button" onClick={onRetry}>Check workspace access again</button>
      : canManage ? <Link href={reconnect ? "/admin/mcp/setup" : "/settings/ai#ai-mcp-access"}>{reconnect ? "Reconnect existing MCP connection" : "Choose connection in AI settings"}</Link> : null}
  </div>;
}
