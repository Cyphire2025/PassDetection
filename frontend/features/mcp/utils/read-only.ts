import type { McpCapability, McpOverview } from "../api/mcp.api";

/** An older/uncertain response must not reveal capabilities beyond lookup. */
export function isMcpReadOnlyMode(overview: Pick<McpOverview, "read_only_mode">): boolean {
  return overview.read_only_mode !== false;
}

export function effectiveMcpCapabilities(overview: McpOverview): McpCapability[] {
  const capabilities = overview.effective_capabilities ?? overview.capabilities;
  return isMcpReadOnlyMode(overview) ? capabilities.filter((scope) => scope === "mcp:read") : capabilities;
}
