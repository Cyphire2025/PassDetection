import type { McpCapability, McpConnection, McpInventory, McpOverview } from "../api/mcp.api";
import { effectiveMcpCapabilities } from "../utils/read-only";

export const CODEX_CLIENT_ID = "global-connects-desktop";
export const CODEX_CALLBACK = "http://127.0.0.1:8765/callback";

export function accessStatus(overview: McpOverview, connections: McpConnection[], uncertain: boolean, partial: boolean) {
  if (uncertain) return { title: "Access status unavailable", description: "Refresh the status before relying on this saved authorization.", authorized: false };
  if (!overview.deployment_enabled) return { title: "Not available", description: "Codex access is not enabled for this website. Contact your administrator for setup.", authorized: false };
  if (!overview.enabled || overview.emergency_disabled) return { title: "Access paused", description: "All Codex connections are paused. Your saved connections and application data are retained.", authorized: false };
  if (connections.some((connection) => connection.status === "active" && connection.capabilities.some((capability) => effectiveMcpCapabilities(overview).includes(capability)))) return { title: "Codex is authorized", description: "A saved connection has access for your account. This does not tell us whether Codex is open or online.", authorized: true };
  if (partial) return { title: "More connections to check", description: "There is no usable Codex authorization on this page. Check the other connection pages before signing in again.", authorized: false };
  if (connections.some((connection) => connection.status === "active")) return { title: "No available permissions", description: "Your saved connection has no permissions enabled on this website. Review its access in Advanced or sign in again.", authorized: false };
  return { title: "Sign-in needed", description: "Connect Codex to this account, then return here to check its access.", authorized: false };
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
  return connections.some((connection) => connection.status === "active" && capabilities.every((capability) => connection.capabilities.includes(capability)));
}
