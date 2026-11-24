export const MCP_CAPABILITIES = {
  "mcp:read": {
    label: "Look up information",
    description: "Find groups, check passenger details and see recorded activity."
  },
  "mcp:export": {
    label: "Download reports",
    description: "Create and download the reports you ask for."
  },
  "mcp:upload": {
    label: "Use selected files",
    description: "Use files you choose for an available task."
  },
  "mcp:change": {
    label: "Make changes",
    description: "Create or update records for tasks you request."
  },
  "mcp:communicate": {
    label: "Send messages",
    description: "Send the messages you explicitly ask it to send."
  },
  "mcp:diagnose": {
    label: "Investigate problems",
    description: "Read limited, filtered technical information to help investigate a problem."
  },
} as const;

export type McpCapability = keyof typeof MCP_CAPABILITIES;
