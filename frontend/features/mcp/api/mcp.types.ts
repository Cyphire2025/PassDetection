import type { McpCapability } from "./mcp-capabilities";

export interface McpOverview {
  enabled: boolean;
  deployment_enabled: boolean;
  emergency_disabled: boolean;
  resource: string;
  capabilities: McpCapability[];
  approved_clients: Record<string, string[]>;
  direct_clients?: Record<string, string[]>;
  client_names?: Record<string, string>;
  environment: string;
  revision: string | null;
  observed_at: string;
  qualification: string;
  read_only_mode?: boolean;
  effective_capabilities?: McpCapability[];
  permission_controls_available?: boolean;
}

export interface McpReadSection {
  id: string;
  label: string;
  supported: boolean;
  tool_names: string[];
  coverage_description?: string;
  metadata_only?: boolean;
  tool_requirements?: {
    name: string;
    required_sections: string[];
  }[];
}

export interface McpReadAccess {
  read_only_mode: boolean;
  effective_capabilities: McpCapability[];
  allowed_read_sections: string[];
  revision: number;
  sections: McpReadSection[];
  connection_metadata_tools: string[];
  environment: string;
  backend_revision: string | null;
  observed_at: string;
}

export interface McpReadAccessUpdate {
  allowed_read_sections: string[];
  expected_revision: number;
}

export interface McpConnection {
  id: string;
  user_id: string;
  client_id: string;
  name: string;
  capabilities: McpCapability[];
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  status: "active" | "disabled" | "expired" | "revoked";
  enabled?: boolean;
  device_platform?: McpDevicePlatform | null;
  read_enabled?: boolean;
  write_enabled?: boolean;
  allowed_read_sections?: string[] | null;
  allowed_write_sections?: string[];
  permission_revision?: number;
}

export type McpDevicePlatform = "Windows" | "macOS" | "Other";

export type McpRequestStatus = "pending" | "approved" | "rejected" | "expired" | "finalized";

export interface McpConnectionRequest {
  id: string;
  name: string;
  device_platform: McpDevicePlatform;
  client_name: string;
  comparison_code: string;
  status: McpRequestStatus;
  requested_capabilities: McpCapability[];
  approved_capabilities?: McpCapability[] | null;
  created_at: string;
  expires_at: string;
  decided_at?: string | null;
  connection_id?: string | null;
}

export interface McpRequestApproval {
  name: string;
  device_platform: McpDevicePlatform;
  capabilities: McpCapability[];
  read_enabled?: boolean;
  write_enabled?: boolean;
  allowed_read_sections?: string[] | null;
  allowed_write_sections?: string[];
}

export interface McpRequestCallback {
  redirect_url: string;
  client_id: string;
  redirect_uri: string;
  resource: string;
  state: string;
}

export interface McpActivity {
  id: string;
  action: string;
  result: string;
  entity_id: string | null;
  created_at: string;
}

export interface McpPage<T> {
  items: T[];
  next_offset: number | null;
}

export interface McpOperation {
  id: string;
  operation: string;
  workflow_id: string;
  connection_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "unknown";
  progress: number;
  stage: string;
  revision: number;
  created_entities: {
    entity_type: string;
    entity_id: string;
    path: string;
  }[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface McpArtifact {
  id: string;
  connection_id: string | null;
  group_id: string | null;
  direction: "upload" | "export";
  kind?: "artifact" | "contact_workbook" | "whatsapp_header";
  agency_id?: string;
  broadcast_id?: string | null;
  operation_id?: string | null;
  sha256?: string;
  attempt_deadline?: string | null;
  purpose: string;
  filename: string;
  byte_size: number;
  created_at: string;
  expires_at: string;
  status: "available" | "expired" | "delivered" | "staged" | "queued" | "running" | "ingested" | "ingestion_failed" | "imported" | "uploading" | "ready" | "failed" | "unknown";
  delivered_at: string | null;
}

export interface McpInventory {
  tool_count: number;
  environment: string;
  revision: string | null;
  qualification: string;
  tools: {
    name: string;
    description: string | null;
    capability: string;
    deployment_available: boolean;
    read_only: boolean;
    qualification: string;
    required_read_sections?: string[];
    section_access_allowed?: boolean;
  }[];
  file_transports: {
    name: string;
    capability: string;
    required_capabilities?: string[];
    business_ingestion?: boolean;
  }[];
}

export type { McpCapability } from "./mcp-capabilities";
