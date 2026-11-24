export interface GroupPassengerQrCode {
  passenger_id: string;
  client_name: string;
  client_email: string | null;
  client_phone: string | null;
  departure_city: string | null;
  coordinator_id: string | null;
  coordinator_name: string | null;
  qr_status: "not_generated" | "active" | "inactive" | "expired" | "revoked" | string;
  qr_token_version: number | null;
  qr_created_at: string | null;
  qr_expires_at: string | null;
  qr_revoked_at: string | null;
  qr_payload: string | null;
}

export interface PassengerQrToken {
  passenger_id: string;
  status: GroupPassengerQrCode["qr_status"];
  token_version: number;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  qr_payload: string | null;
}

export interface GroupPassengerQrCodes {
  group_id: string;
  group_name: string;
  generated_at: string;
  passengers: GroupPassengerQrCode[];
}

export interface QrDeliveryPreviewRecipient {
  passenger_id: string;
  passenger_name: string;
  passport_number: string | null;
  qr_token_id: string | null;
  qr_token_version: number | null;
  qr_status: string;
  recipient_id: string | null;
  broadcast_group_id: string | null;
  broadcast_name: string | null;
  phone_number: string | null;
  delivery_id: string | null;
  delivery_status: string;
  eligible: boolean;
  reason: string;
  error_message: string | null;
  message_preview: string | null;
}

export interface QrDeliveryPreview {
  group_id: string;
  template_name: string | null;
  template_configured: boolean;
  linked_broadcast_count: number;
  can_send: boolean;
  configuration_error: string | null;
  message_content: string;
  summary: {
    total_passengers: number;
    ready: number;
    retryable: number;
    already_sent: number;
    in_progress: number;
    blocked: number;
    ambiguous_recipients?: number;
  };
  recipients: QrDeliveryPreviewRecipient[];
}

export interface SendQrBroadcastResponse {
  send_batch_id: string | null;
  queued_count: number;
  skipped_count: number;
  message: string;
}
