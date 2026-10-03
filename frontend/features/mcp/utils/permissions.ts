import type { McpCapability, McpConnection, McpPermissions, McpPermissionUpdate } from "../api/mcp.api";

export const MCP_WRITE_CAPABILITIES: readonly McpCapability[] = ["mcp:change", "mcp:upload", "mcp:export", "mcp:communicate"];

export function hasWriteScope(capabilities: readonly McpCapability[]) {
  return capabilities.some((scope) => MCP_WRITE_CAPABILITIES.includes(scope));
}

export function validConnectionPermissions(connection: McpConnection) {
  return Number.isInteger(connection.permission_revision) && (connection.permission_revision ?? 0) >= 1
    && typeof connection.read_enabled === "boolean" && typeof connection.write_enabled === "boolean"
    && (connection.allowed_read_sections === null || stringList(connection.allowed_read_sections))
    && stringList(connection.allowed_write_sections);
}

function stringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string" && item.length > 0)
    && new Set(value).size === value.length;
}

export function validPermissions(data: McpPermissions) {
  if (!Number.isInteger(data.permission_revision) || data.permission_revision < 1
    || typeof data.read_enabled !== "boolean" || typeof data.write_enabled !== "boolean"
    || typeof data.write_available !== "boolean" || !Array.isArray(data.section_catalog)
    || !Array.isArray(data.write_tool_requirements)
    || !stringList(data.allowed_read_sections) || !stringList(data.allowed_write_sections)
    || !stringList(data.allowed_write_tools)) return false;
  if (data.section_catalog.some((section) => !section || typeof section.id !== "string" || !section.id
    || typeof section.label !== "string" || typeof section.read_supported !== "boolean" || typeof section.write_supported !== "boolean"
    || typeof section.read_description !== "string" || typeof section.write_description !== "string"
    || !stringList(section.read_tool_names) || !stringList(section.write_tool_names))
    || new Set(data.section_catalog.map((section) => section.id)).size !== data.section_catalog.length) return false;
  const read = new Set(data.section_catalog.filter((section) => section.read_supported).map((section) => section.id));
  const write = new Set(data.section_catalog.filter((section) => section.write_supported).map((section) => section.id));
  if (data.write_tool_requirements.some((tool) => !tool || typeof tool.name !== "string" || !tool.name
    || !stringList(tool.required_sections)
    || tool.required_sections.some((section) => !write.has(section)))
    || new Set(data.write_tool_requirements.map((tool) => tool.name)).size !== data.write_tool_requirements.length) return false;
  const tools = new Set(data.write_tool_requirements.map((tool) => tool.name));
  return data.allowed_read_sections.every((section) => read.has(section))
    && data.allowed_write_sections.every((section) => write.has(section))
    && data.allowed_write_tools.every((name) => tools.has(name)
      && data.write_tool_requirements.find((tool) => tool.name === name)!.required_sections.every((section) => data.allowed_write_sections.includes(section)));
}

export function writeToolsForSections(data: McpPermissions, sections: readonly string[]) {
  const allowed = new Set(sections);
  return [...new Set(data.write_tool_requirements.filter((tool) => tool.required_sections.every((section) => allowed.has(section))).map((tool) => tool.name))].sort();
}

export function deviceWriteSections(data: McpPermissions) {
  return data.section_catalog.map((section) => ({ ...section,
    write_allowed_by_settings: data.allowed_write_sections.includes(section.id),
    write_description: section.write_supported && !data.allowed_write_sections.includes(section.id)
      ? "This action is turned off in global Write settings. Enable it there before allowing it on this device." : section.write_description }));
}

export function permissionUpdate(data: McpPermissions): McpPermissionUpdate {
  return { expected_revision: data.permission_revision, read_enabled: data.read_enabled, write_enabled: data.write_enabled,
    allowed_read_sections: [...data.allowed_read_sections].sort(), allowed_write_sections: [...data.allowed_write_sections].sort(),
    allowed_write_tools: [...data.allowed_write_tools].sort() };
}

export function samePermissionUpdate(left: McpPermissionUpdate, right: McpPermissionUpdate) {
  return JSON.stringify(left) === JSON.stringify(right);
}
