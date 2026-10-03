import type { McpCapability, McpConnection, McpInventory, McpOverview } from "../api/mcp.api";
import { effectiveMcpCapabilities } from "../utils/read-only";
import { MCP_WRITE_CAPABILITIES } from "../utils/permissions";

export const CODEX_CLIENT_ID = "global-connects-desktop";
export const CODEX_CALLBACK = "http://127.0.0.1:8765/callback";
export const DIRECT_CODEX_CLIENT_ID = "https://chatgpt.com/oauth/codex/client.json";
export const CHATGPT_CLIENT_ID = "https://chatgpt.com/oauth/client.json";
export function isGlobalConnectsClient(clientId: string) {
  return [CODEX_CLIENT_ID, DIRECT_CODEX_CLIENT_ID, CHATGPT_CLIENT_ID].includes(clientId);
}
export function connectionHasAccess(connection: McpConnection) {
  return connection.status === "active" && connection.enabled !== false;
}
function allowsCapability(connection: McpConnection, capability: McpCapability) {
  if (!connection.capabilities.includes(capability)) return false;
  if (capability === "mcp:read") return connection.read_enabled !== false;
  if (MCP_WRITE_CAPABILITIES.includes(capability)) return connection.write_enabled !== false;
  return true;
}

export function accessStatus(overview: McpOverview, connections: McpConnection[], uncertain: boolean, partial: boolean) {
  if (uncertain) return { title: "Access status unavailable", description: "Refresh the status before relying on this saved authorization.", authorized: false };
  if (!overview.deployment_enabled) return { title: "Not available", description: "MCP access is not enabled for this website. Contact your administrator for setup.", authorized: false };
  if (!overview.enabled || overview.emergency_disabled) return { title: "Access paused", description: "All Codex connections are paused. Your saved connections and application data are retained.", authorized: false };
  if (connections.some((connection) => connectionHasAccess(connection) && effectiveMcpCapabilities(overview).some((capability) => allowsCapability(connection, capability)))) return { title: "Codex is authorized", description: "A saved connection is approved for your account. Its allowances and the section settings determine which actions it may use. This does not tell us whether the app is open or online.", authorized: true };
  if (partial) return { title: "More connections to check", description: "There is no usable Codex authorization on this page. Check the other connection pages before signing in again.", authorized: false };
  if (connections.some(connectionHasAccess)) return { title: "No available permissions", description: "Review this device’s allowances in Devices and the saved read and write settings.", authorized: false };
  if (connections.some((connection) => connection.status === "disabled" || (connection.status === "active" && connection.enabled === false))) return { title: "Your connections are disabled", description: "Enable a saved connection in Devices to allow access again.", authorized: false };
  return { title: "Approval needed", description: "Click Authenticate in your MCP app and ask an administrator to approve the matching request.", authorized: false };
}

export const BUSINESS_EXAMPLES = [
  { key: "read", title: "Look up information", capabilities: ["mcp:read"] as McpCapability[],
    description: "Find groups and check the passport information already saved in Global Connects.",
    prompt: "Show me my groups. Let me choose one, then show its passport list.",
    tools: [{ name: "list_groups", capability: "mcp:read" }, { name: "list_group_passports", capability: "mcp:read" }], transports: [] },
  { key: "export", title: "Download reports", capabilities: ["mcp:read", "mcp:export"] as McpCapability[],
    description: "Prepare a passport Excel report with the fields you choose. Start with a small group or selection; larger requests may need splitting.",
    prompt: "Help me prepare a passport Excel report. Ask me to choose the group and fields before preparing it.",
    tools: [{ name: "inspect_excel_export_options", capability: "mcp:read" }, ...["inspect_excel_export", "prepare_excel_export", "resume_excel_export"].map((name) => ({ name, capability: "mcp:export" }))],
    transports: ["download_prepared_artifact", "acknowledge_verified_delivery"] },
];

export function exampleAvailable(overview: McpOverview, inventory: McpInventory | undefined, example: typeof BUSINESS_EXAMPLES[number]) {
  return overview.deployment_enabled && example.capabilities.every((capability) => overview.capabilities.includes(capability)) && !!inventory
    && example.tools.every((required) => inventory.tools.some((tool) => tool.name === required.name && tool.deployment_available && tool.capability === required.capability))
    && example.transports.every((name) => inventory.file_transports.some((transport) => transport.name === name && transport.capability === "mcp:export"));
}

export function hasPermission(connections: McpConnection[], capabilities: McpCapability[]) {
  return connections.some((connection) => connectionHasAccess(connection) && capabilities.every((capability) => allowsCapability(connection, capability)));
}
