"use client";

import { useDeferredValue, useState } from "react";
import Link from "next/link";
import { ArrowRight, RefreshCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { useBroadcast } from "./broadcast-workspace-shell";
import { historyApi, type HistoryFilter } from "./history.api";
import { RecipientPhoneCell } from "./recipient-controls";
import {
  DeliveryBadge,
  EmptyWorkspace,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

const filters: { id: HistoryFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "sent", label: "Sent" },
  { id: "not_sent", label: "Not sent" },
  { id: "delivery_left", label: "Delivery left" },
  { id: "failed", label: "Failed" },
];

export function TypeRecipientReport({ messageType }: { messageType: string }) {
  const group = useBroadcast();
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const query = useQuery({
    queryKey: [
      "whatsapp",
      "history",
      group.id,
      "type-recipients",
      messageType,
      { filter, q, offset },
    ],
    queryFn: ({ signal }) =>
      historyApi.typeRecipients(
        group.id,
        messageType,
        { status_filter: filter, q, offset, limit: 50 },
        signal,
      ),
    refetchInterval: 15_000,
  });
  return (
    <section className={styles.surface} aria-label="Overall message recipients">
      <div className="space-y-4 p-5">
        <WorkspaceSearch
          value={search}
          onChange={(value) => {
            setSearch(value);
            setOffset(0);
          }}
          label="Search overall recipients"
          placeholder="Search name or WhatsApp number…"
        >
          <Button
            variant="ghost"
            isLoading={query.isFetching && !query.isLoading}
            onClick={() => void query.refetch()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh recipients
          </Button>
        </WorkspaceSearch>
        <div className="flex flex-wrap gap-2">
          {filters.map((item) => (
            <button
              type="button"
              key={item.id}
              aria-pressed={filter === item.id}
              onClick={() => {
                setFilter(item.id);
                setOffset(0);
              }}
              className={`rounded-lg px-3 py-2 text-xs font-medium ${filter === item.id ? "bg-blue-50 text-blue-700 ring-1 ring-blue-200" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
            >
              {item.label}{" "}
              <span className="ml-2 tabular-nums">
                {query.data?.counts[item.id] ?? "—"}
              </span>
            </button>
          ))}
        </div>
        <p className="text-xs leading-5 text-slate-500">
          A successful earlier version keeps a person in Sent. Otherwise their
          latest attempt is shown. Not sent includes recipients with no attempt
          yet and sends still queued. Delivery left is part of Sent. Changing a
          number does not change earlier delivery records.
        </p>
      </div>
      {query.isLoading ? (
        <Skeleton className="m-5 h-60" />
      ) : query.error ? (
        <div className="p-5">
          <ErrorBanner
            message={readErrorMessage(
              query.error,
              "Overall recipients could not be loaded.",
            )}
          />
        </div>
      ) : !query.data?.items.length ? (
        <EmptyWorkspace
          title="No matching recipients"
          description="Try another delivery filter or search."
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>WhatsApp number</th>
                  <th>Overall status</th>
                  <th>
                    <span className="sr-only">Saved send</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((person) => (
                  <tr key={person.recipient_id}>
                    <td className="font-medium text-slate-900">
                      {person.name || "Unnamed recipient"}
                    </td>
                    <td>
                      <RecipientPhoneCell
                        groupId={group.id}
                        recipientId={person.recipient_id}
                        number={person.phone_number}
                        disabled={Boolean(group.is_archived)}
                        editing={editing === person.recipient_id}
                        onEdit={() => setEditing(person.recipient_id)}
                        onDone={() => setEditing(null)}
                      />
                    </td>
                    <td>
                      <DeliveryBadge status={person.status} />
                      {person.error_message && (
                        <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">
                          {person.error_message}
                        </p>
                      )}
                    </td>
                    <td>
                      {person.message_id ? (
                        <Link
                          href={`${ROUTES.dashboard.whatsappBroadcastHistory(group.id)}?message=${encodeURIComponent(person.message_id)}`}
                          className="inline-flex items-center gap-2 whitespace-nowrap text-xs font-medium text-blue-700"
                        >
                          View saved send
                          <ArrowRight className="h-3.5 w-3.5" />
                        </Link>
                      ) : (
                        <span className="text-xs text-slate-400">
                          No send recorded
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <WorkspacePagination
            total={query.data.total}
            offset={offset}
            limit={50}
            onChange={setOffset}
            label="Overall recipients"
          />
        </>
      )}
    </section>
  );
}
