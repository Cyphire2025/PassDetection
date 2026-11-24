import type { ClientManagerAccount } from "../types";

export type DetailTab = "overview" | "sessions" | "audit";
export type Confirmation = "suspend" | "reactivate" | "revoke" | "delete" | null;

export interface ClientManagerDetailsProps {
  open: boolean;
  agencyId: string | null;
  manager: ClientManagerAccount | null;
  onClose: () => void;
  onEdit: () => void;
  onUpdated: (manager: ClientManagerAccount) => void;
}

