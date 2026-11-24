import type { WhatsAppRecipient, WhatsAppSupportContact } from './recipients';

export interface WhatsAppBroadcastGroup {
  id: string;
  name: string;
  is_archived?: boolean;
  archived_at?: string | null;
  has_import_only_source?: boolean;
  source_contact_count?: number;
  /** Active, valid recipients that can receive a message. */
  recipient_count: number;
  /** Complete visible roster: valid recipients plus rejected import rows. */
  total_contact_count: number;
  recipient_opt_in_confirmed: boolean;
  available_matching_fields?: WhatsAppMatchingFieldOption[];
  created_at: string;
  updated_at: string;
}

export interface WhatsAppMatchingFieldOption {
  key: string;
  label: string;
}

export interface WhatsAppLinkedClientGroup {
  id: string;
  name: string;
  import_only?: boolean;
  status: string;
}

export interface WhatsAppBroadcastGroupDetail extends WhatsAppBroadcastGroup {
  recipients: WhatsAppRecipient[];
  support_contacts: WhatsAppSupportContact[];
  rejected_contact_count: number;
  linked_client_groups?: WhatsAppLinkedClientGroup[];
}
