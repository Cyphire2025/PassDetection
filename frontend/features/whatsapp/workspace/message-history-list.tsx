"use client";

import { ArrowRight, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import {
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { formatMessageType } from "../utils/message-types";
import { useBroadcast } from "./broadcast-workspace-shell";
import { historyApi } from "./history.api";
import {
  EmptyWorkspace,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
  workspaceDate,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function MessageHistoryList() {
  const group = useBroadcast();
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["whatsapp", "history", group.id, { q, offset }],
    queryFn: ({ signal }) =>
      historyApi.list(group.id, { q, offset, limit: 25 }, signal),
    refetchInterval: 15_000,
  });
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">
          Delivery history
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Every send has its own record, including repeated messages of the same
          type.
        </p>
      </div>
      <section className={styles.surface}>
        <div className="p-5">
          <WorkspaceSearch
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            label="Search message history"
            placeholder="Search messages or message types…"
          >
            <Button
              variant="ghost"
              isLoading={query.isFetching && !query.isLoading}
              onClick={() => void query.refetch()}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </WorkspaceSearch>
        </div>
        {query.isLoading ? (
          <Skeleton className="m-5 h-60" />
        ) : query.error ? (
          <div className="p-5">
            <ErrorBanner
              message={readErrorMessage(
                query.error,
                "Message history could not be loaded.",
              )}
            />
          </div>
        ) : !query.data?.items.length ? (
          <EmptyWorkspace
            title={q ? "No matching messages" : "No messages sent yet"}
            description={
              q
                ? "Try a message type or a phrase from the message."
                : "Your first send will appear here with its own recipient-level delivery report."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th>Message</th>
                  <th>Started at</th>
                  <th>Recipients</th>
                  <th>Sent</th>
                  <th>Failed</th>
                  <th>
                    <span className="sr-only">Open report</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((entry) => (
                  <tr key={entry.id}>
                    <td className="max-w-sm">
                      <Link
                        href={`?message=${encodeURIComponent(entry.id)}`}
                        className="font-medium text-slate-900 hover:text-blue-700"
                      >
                        {formatMessageType(entry.message_type)}
                      </Link>
                      <p className="mt-1 line-clamp-1 text-xs text-slate-500">
                        {entry.message_preview || "Saved message"}
                      </p>
                    </td>
                    <td className="whitespace-nowrap text-xs text-slate-500">
                      {workspaceDate(entry.created_at)}
                    </td>
                    <td className="tabular-nums text-slate-600">
                      {entry.counts.all}
                    </td>
                    <td className="tabular-nums text-slate-600">
                      {entry.counts.sent}
                    </td>
                    <td>
                      <span
                        className={`tabular-nums ${entry.counts.failed ? "font-medium text-red-600" : "text-slate-400"}`}
                      >
                        {entry.counts.failed}
                      </span>
                    </td>
                    <td>
                      <Link
                        aria-label={`View delivery for ${formatMessageType(entry.message_type)} sent ${workspaceDate(entry.created_at)}`}
                        href={`?message=${encodeURIComponent(entry.id)}`}
                        className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-blue-700"
                      >
                        View delivery
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Link>
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
          limit={25}
          onChange={setOffset}
          busy={query.isFetching}
          label="Message history"
        />
      </section>
    </div>
  );
}
