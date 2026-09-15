"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { getAnnouncementNotificationStatus } from "../api/announcement-notification-status.api";
import { formatGcDateTime } from "../utils";

const failureLabels: Record<string, string> = {
  no_active_registration: "No registered, authorized device is available",
  announcement_unpublished: "The announcement was withdrawn",
  recipient_access_revoked: "The recipient no longer has access",
  invalid_public_payload: "The notification content could not be sent safely",
  token_decryption_failed: "The server could not read the saved device registration",
  receipt_expired: "Provider confirmation did not arrive before the deadline",
  receipt_not_ready: "Provider confirmation is still pending",
  provider_disabled: "Phone notifications are disabled on the server",
  provider_unavailable: "The notification provider is unavailable",
  provider_http_error: "The notification provider returned an error",
  provider_rejected: "The notification provider rejected the request",
  provider_malformed_response: "The notification provider returned an unreadable response",
  provider_ticket_error: "The notification provider did not accept the request",
  provider_receipt_error: "The notification provider reported a delivery problem",
  provider_timeout: "The notification provider did not respond in time",
  DeviceNotRegistered: "The device registration is no longer valid; open the app to register again",
  MessageTooBig: "The notification is too large",
  MessageRateExceeded: "Too many notifications were sent to this device",
  MismatchSenderId: "The device registration belongs to a different notification project",
  InvalidCredentials: "The notification provider rejected the server credentials",
  provider_outcome_unknown: "The send outcome is unknown; no automatic resend will be attempted",
  source_recheck_deferred: "The announcement is being checked again before sending",
  fcm_connection_unavailable: "The server could not connect to Google",
  fcm_quota_exceeded: "Google's sending limit was reached",
  fcm_unavailable: "Google's notification service is unavailable",
  fcm_sender_id_mismatch: "The device registration belongs to a different Firebase project",
  fcm_authentication_failed: "Google rejected the server credentials or permissions",
  fcm_invalid_argument: "Google rejected the notification format or device registration",
  fcm_provider_rejected: "Google rejected the notification request",
  fcm_credentials_missing: "Firebase server credentials are missing; contact the administrator",
  fcm_credentials_invalid: "Firebase server credentials are invalid; contact the administrator",
  fcm_credentials_project_or_type_mismatch: "Firebase server credentials do not match the configured project or account type",
  fcm_credentials_path_must_be_absolute: "The Firebase server credential file location is not configured correctly",
  fcm_credentials_unavailable: "The server could not use the Firebase credentials; contact the administrator",
};

export function AnnouncementNotificationStatusPanel({ agencyId, groupId, announcementId, version }: {
  agencyId: string | null; groupId: string; announcementId: string; version: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const query = useQuery({
    queryKey: ["gc-app", agencyId, groupId, "announcement-notification-status", announcementId, version],
    queryFn: ({ signal }) => getAnnouncementNotificationStatus(agencyId, groupId, announcementId, signal),
    enabled: expanded,
    refetchInterval: expanded ? 15_000 : false,
    retry: false,
  });
  const data = query.data;
  return <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3" onToggle={(event) => setExpanded(event.currentTarget.open)}>
    <summary className="cursor-pointer text-sm font-medium text-slate-800">Notification delivery status</summary>
    {expanded && <div className="mt-3 space-y-3 text-xs text-slate-600">
      <p>Publishing makes the announcement available in the app. Provider confirmation records the notification handoff; it does not prove that the phone displayed a banner.</p>
      {query.isError && <p role="alert" className="text-red-700">Notification status could not be loaded. The latest delivery status is unavailable; refresh to check again.</p>}
      {query.isPending && <p role="status">Checking notification delivery…</p>}
      {data && <>
        {!data.provider_enabled && <p role="status" className="rounded-md bg-amber-100 p-2 text-amber-900">Phone notifications are disabled on the server. The announcement can still appear inside the app.</p>}
        <h4 className="font-semibold text-slate-800">Recipients</h4>
        <Counts items={[
          ["Total recipients", data.recipient_counts.total], ["Queued recipients", data.recipient_counts.queued],
          ["Recorded missing device registrations", data.recipient_counts.no_active_registration],
          ["Recipients with an accepted notification", data.recipient_counts.sent], ["Read in app", data.recipient_counts.read],
          ["Recipients with an unknown send outcome", data.recipient_counts.unknown ?? 0],
          ["Failed recipients", data.recipient_counts.failed], ["Cancelled recipients", data.recipient_counts.cancelled],
        ]} />
        <h4 className="font-semibold text-slate-800">Device deliveries</h4>
        <Counts items={[
          ["Total device deliveries", data.device_delivery_counts.total], ["Submitting", data.device_delivery_counts.submitting],
          ["Waiting to retry", data.device_delivery_counts.retry], ["Awaiting provider confirmation", data.device_delivery_counts.receipt_pending],
          ["Provider receipt received; phone display unconfirmed", data.device_delivery_counts.delivered], ["Failed device deliveries", data.device_delivery_counts.failed],
          ["Accepted by Google; phone display unconfirmed", data.device_delivery_counts.provider_accepted ?? 0],
          ["Unknown send outcome; not automatically resent", data.device_delivery_counts.unknown ?? 0],
          ["Cancelled device deliveries", data.device_delivery_counts.cancelled],
        ]} />
        {((data.recipient_counts.unknown ?? 0) > 0 || (data.device_delivery_counts.unknown ?? 0) > 0) && <p className="rounded-md bg-amber-100 p-2 text-amber-900">Notifications with an unknown outcome are not automatically resent, to avoid duplicate alerts. Check the recipient&apos;s app before arranging another notification.</p>}
        {data.failures.length > 0 && <ul className="list-inside list-disc">{data.failures.map((failure) => <li key={`${failure.scope}:${failure.code}`}>
          {failureLabels[failure.code] ?? "Another notification problem was recorded"}: {failure.count} ({failure.scope === "device" ? "device deliveries" : "recipients"})
        </li>)}</ul>}
        <p>Checked {formatGcDateTime(data.checked_at)}</p>
      </>}
      <Button type="button" size="sm" variant="secondary" isLoading={query.isFetching} onClick={() => void query.refetch()}>Refresh notification status</Button>
    </div>}
  </details>;
}

function Counts({ items }: { items: Array<[string, number]> }) {
  return <dl className="grid grid-cols-1 gap-1 sm:grid-cols-2">{items.map(([label, count]) => <div key={label} className="flex justify-between gap-3"><dt>{label}</dt><dd className="font-semibold text-slate-900">{count}</dd></div>)}</dl>;
}
