export interface AdminOverview {
  agencies: number;
  users: number;
  client_groups: number;
  passport_submissions: number;
  pending_review: number;
  client_submitted: number;
  failed: number;
}

export interface ManagerAccount {
  id: string;
  full_name: string;
  email: string;
  role: "agency_manager";
  agency_id: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  created_groups: ManagerGroupAccess[];
  assigned_groups: ManagerGroupAccess[];
  credential_state: "invited" | "active";
  activation_token?: string | null;
}

export interface ManagerGroupAccess {
  id: string;
  agency_id: string;
  name: string;
  status: string;
  created_by_user_id: string | null;
}

export interface ManagedAccount {
  id: string;
  full_name: string;
  email: string;
  role: "agency_manager" | "agency_staff" | "agency_coordinator";
  agency_id: string | null;
  agency_name: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  credential_state: "invited" | "active";
  activation_token?: string | null;
}

export interface StaffAccount {
  id: string;
  full_name: string;
  email: string;
  role: "agency_staff";
  agency_id: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  credential_state?: "invited" | "active";
  created_groups: ManagerGroupAccess[];
  assigned_groups: ManagerGroupAccess[];
}

export interface DeleteManagedAccountResponse {
  account_id: string;
  result: "deleted" | "access_removed" | string;
  preserved_history: boolean;
}

export interface CreateManagerRequest {
  full_name: string;
  email: string;
}

export interface CreateStaffRequest {
  full_name: string;
  email: string;
}

export interface DeleteManagerResponse {
  deleted_manager_id: string;
  deleted_owned_data: boolean;
  deleted_client_groups: number;
  deleted_passport_submissions: number;
  deleted_processing_jobs: number;
  deleted_notifications: number;
  deleted_audit_logs: number;
  deleted_storage_objects: number;
}
