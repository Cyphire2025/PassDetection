import type { McpConnection, McpPermissions } from "../api/mcp.api";

export function permissionFixture(overrides: Partial<McpPermissions> = {}): McpPermissions {
  const section_catalog = [
    { id: "all_groups", label: "All groups", read_supported: true, write_supported: true },
    { id: "group_links", label: "Group links", read_supported: true, write_supported: true },
    { id: "exports", label: "Exports", read_supported: false, write_supported: true },
    { id: "menu", label: "Menu", read_supported: true, write_supported: true },
    { id: "profile", label: "Profile", read_supported: false, write_supported: false },
  ].map((section) => ({ ...section, read_description: section.read_supported ? `Look up ${section.label}.` : "No available read actions.",
    write_description: section.write_supported ? `Reviewed actions for ${section.label}.` : "No available write actions.",
    read_tool_names: [], write_tool_names: [] }));
  return { read_enabled: true, write_enabled: false, allowed_read_sections: ["all_groups", "menu"],
    allowed_write_sections: ["all_groups", "exports"], allowed_write_tools: ["create_group", "prepare_excel_export", "create_native_upload"],
    permission_revision: 7, write_available: true, section_catalog,
    write_tool_requirements: [
      { name: "create_group", required_sections: ["all_groups"] },
      { name: "configure_group_link", required_sections: ["all_groups", "group_links"] },
      { name: "prepare_excel_export", required_sections: ["exports"] },
      { name: "create_menu_dish", required_sections: ["menu"] },
      { name: "create_native_upload", required_sections: [] },
    ], ...overrides };
}

export function connectionFixture(overrides: Partial<McpConnection> = {}): McpConnection {
  return { id: "windows-a", name: "Office Windows", user_id: "admin-a", client_id: "native-codex", device_platform: "Windows",
    capabilities: ["mcp:read", "mcp:export", "mcp:change"], enabled: true, status: "active", revoked_at: null, last_used_at: null,
    created_at: "2026-10-03T00:00:00Z", expires_at: "2026-10-10T00:00:00Z", read_enabled: true, write_enabled: false,
    allowed_read_sections: null, allowed_write_sections: [], permission_revision: 3, ...overrides };
}
