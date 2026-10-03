export interface McpPermissionSection {
  id: string;
  label: string;
  read_supported: boolean;
  write_supported: boolean;
  read_description: string;
  write_description: string;
  read_tool_names: string[];
  write_tool_names: string[];
}

export interface McpPermissions {
  read_enabled: boolean;
  write_enabled: boolean;
  allowed_read_sections: string[];
  allowed_write_sections: string[];
  allowed_write_tools: string[];
  permission_revision: number;
  section_catalog: McpPermissionSection[];
  write_tool_requirements: { name: string; required_sections: string[] }[];
  write_available: boolean;
}

export interface McpPermissionUpdate {
  expected_revision: number;
  read_enabled: boolean;
  write_enabled: boolean;
  allowed_read_sections: string[];
  allowed_write_sections: string[];
  allowed_write_tools: string[];
}

export interface McpConnectionPermissionUpdate {
  id: string;
  expected_revision: number;
  read_enabled: boolean;
  write_enabled: boolean;
  allowed_read_sections: string[] | null;
  allowed_write_sections: string[];
}
