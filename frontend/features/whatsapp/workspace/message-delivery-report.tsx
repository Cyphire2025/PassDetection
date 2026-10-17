"use client";

import { ROUTES } from "@/constants/routes";
import { ArrowLeft, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import {
  DialogFrame,
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { formatMessageType } from "../utils/message-types";
import { useBroadcast } from "./broadcast-workspace-shell";
import {
  historyApi,
  type HistoryFilter,
  type HistoryRecipient,
} from "./history.api";
import { RecipientPhoneCell } from "./recipient-controls";
import { ComposerPreview } from "./composer-primitives";
import { HistoricalResend } from "./historical-resend-dialog";
import {
  DeliveryBadge,
  EmptyWorkspace,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
  workspaceDate,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

const historyFilters: {
  id: HistoryFilter;
  label: string;
  description: string;
}[] = [
  {
    id: "all",
    label: "All",
    description: "Every recipient included in this send.",
  },
  {
    id: "sent",
    label: "Sent",
    description: "Accepted by WhatsApp, including delivered and read messages.",
  },
  {
    id: "not_sent",
    label: "Not sent",
    description: "Queued or still being submitted.",
  },
  {
    id: "delivery_left",
    label: "Delivery left",
    description:
      "Sent to WhatsApp; delivery to the recipient has not been confirmed.",
  },
  {
    id: "failed",
    label: "Failed",
    description:
      "Failed or unresolved attempts. Unconfirmed outcomes cannot be automatically resent.",
  },
];

export function MessageDeliveryPage({ messageId }: { messageId: string }) {
  const group = useBroadcast();
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const [resending, setResending] = useState<HistoryRecipient | null>(null);
  const [viewingMessage, setViewingMessage] = useState(false);
  const summary = useQuery({
    queryKey: ["whatsapp", "history", group.id, "entry", messageId],
    queryFn: ({ signal }) => historyApi.entry(group.id, messageId, signal),
  });
  const query = useQuery({
    queryKey: [
      "whatsapp",
      "history",
      group.id,
      messageId,
      { filter, q, offset },
    ],
    queryFn: ({ signal }) =>
      historyApi.recipients(
        group.id,
        messageId,
        { status_filter: filter, q, offset, limit: 50 },
        signal,
      ),
    refetchInterval: 10_000,
  });
  return (
    <div className="space-y-5">
      <Link
        href={ROUTES.dashboard.whatsappBroadcastHistory(group.id)}
        className="inline-flex items-center gap-2 text-xs font-medium text-slate-500 hover:text-blue-700"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        All messages
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            {summary.data
              ? formatMessageType(summary.data.message_type)
              : "Message delivery"}
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            {summary.data
              ? workspaceDate(summary.data.created_at)
              : "Recipient-level report for this individual send"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            disabled={!summary.data}
            onClick={() => setViewingMessage(true)}
          >
            View message
          </Button>
          <Button
            variant="secondary"
            isLoading={query.isFetching && !query.isLoading}
            onClick={() => void query.refetch()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh status
          </Button>
        </div>
      </div>
      <section className={styles.surface}>
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap gap-2">
            {historyFilters.map((item) => (
              <button
                key={item.id}
                onClick={() => {
                  setFilter(item.id);
                  setOffset(0);
                }}
                aria-pressed={filter === item.id}
                aria-label={`${item.label} (${query.data?.counts[item.id] ?? "loading"})`}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${filter === item.id ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
              >
                {item.label}
                <span className="tabular-nums opacity-75">
                  {query.data?.counts[item.id] ?? "—"}
                </span>
              </button>
            ))}
          </div>
          <p className="text-xs leading-5 text-slate-500">
            {historyFilters.find((item) => item.id === filter)?.description}
          </p>
          <WorkspaceSearch
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            label="Search delivery recipients"
            placeholder="Search recipient name or WhatsApp number…"
          />
        </div>
        {query.isLoading ? (
          <Skeleton className="m-5 h-60" />
        ) : query.error ? (
          <div className="p-5">
            <ErrorBanner
              message={readErrorMessage(
                query.error,
                "Delivery details could not be loaded.",
              )}
            />
          </div>
        ) : !query.data?.items.length ? (
          <EmptyWorkspace
            title="No recipients match this filter"
            description="Choose another delivery filter or clear your search."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>WhatsApp number</th>
                  <th>Delivery status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((recipient) => (
                  <tr key={recipient.message_log_id}>
                    <td>
                      <p className="font-medium text-slate-900">
                        {recipient.name || "Unnamed recipient"}
                      </p>
                      {recipient.removed && (
                        <p className="mt-1 text-xs text-slate-400">
                          Removed from broadcast
                        </p>
                      )}
                    </td>
                    <td>
                      <RecipientPhoneCell
                        groupId={group.id}
                        recipientId={recipient.recipient_id}
                        number={recipient.current_phone_number}
                        editing={editing === recipient.message_log_id}
                        disabled={group.is_archived || recipient.removed}
                        onEdit={() => setEditing(recipient.message_log_id)}
                        onDone={() => setEditing(null)}
                      />
                      {recipient.current_phone_number !==
                        recipient.phone_number && (
                        <p className="mt-1 text-xs text-slate-400">
                          Originally sent to {recipient.phone_number}
                        </p>
                      )}
                    </td>
                    <td>
                      <DeliveryBadge status={recipient.status} />
                      {recipient.error_message && (
                        <p className="mt-1.5 max-w-sm text-xs leading-5 text-slate-500">
                          {recipient.error_message}
                        </p>
                      )}
                      {["delivery_unknown", "stalled"].includes(
                        recipient.status,
                      ) && (
                        <p className="mt-1.5 max-w-xs text-xs leading-5 text-amber-700">
                          Delivery is unconfirmed. Resending is paused to avoid
                          duplicates.
                        </p>
                      )}
                    </td>
                    <td>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={!recipient.can_resend || !summary.data}
                        onClick={() => setResending(recipient)}
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                        {recipient.status === "failed" ? "Retry" : "Resend"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <WorkspacePagination
          total={query.data?.total ?? 0}
          offset={offset}
          limit={50}
          onChange={setOffset}
          busy={query.isFetching}
          label="Delivery recipients"
        />
      </section>
      {resending && summary.data && (
        <HistoricalResend
          groupId={group.id}
          entry={summary.data}
          recipient={resending}
          onClose={() => setResending(null)}
        />
      )}
      {viewingMessage && summary.data && (
        <DialogFrame
          title="Message content"
          description="A saved example from this individual send."
          onClose={() => setViewingMessage(false)}
        >
          <ComposerPreview
            message={
              summary.data.rendered_message ?? summary.data.message_preview
            }
            current
          />
          <p className="mt-3 text-xs leading-5 text-slate-500">
            Each recipient’s saved wording is shown when retrying or resending
            their message.
          </p>
        </DialogFrame>
      )}
    </div>
  );
}
