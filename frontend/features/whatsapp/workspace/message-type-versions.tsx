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
import { historyApi } from "./history.api";
import {
  EmptyWorkspace,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
  workspaceDate,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function MessageTypeVersions({ messageType }: { messageType: string }) {
  const group = useBroadcast();
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search);
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: [
      "whatsapp",
      "history",
      group.id,
      "versions",
      messageType,
      { q, offset },
    ],
    queryFn: ({ signal }) =>
      historyApi.versions(
        group.id,
        messageType,
        { q, offset, limit: 25 },
        signal,
      ),
    refetchInterval: 15_000,
  });
  return (
    <section className={styles.surface} aria-label="Message versions">
      <div className="space-y-3 p-5">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">
            Every version, separately
          </h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Each recorded send gets its own version and delivery report.
            Identical wording stays separate. Resends may include a smaller
            audience. Older records without a saved send identifier are labeled
            Legacy record.
          </p>
        </div>
        <WorkspaceSearch
          value={search}
          onChange={(value) => {
            setSearch(value);
            setOffset(0);
          }}
          label="Search message versions"
          placeholder="Search the message content…"
        >
          <Button
            variant="ghost"
            isLoading={query.isFetching && !query.isLoading}
            onClick={() => void query.refetch()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh versions
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
              "Message versions could not be loaded.",
            )}
          />
        </div>
      ) : !query.data?.items.length ? (
        <EmptyWorkspace
          title="No versions found"
          description={
            q
              ? "Try a different phrase."
              : "The first send of this message type will appear here."
          }
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Sent on</th>
                  <th>Recipients</th>
                  <th>Sent</th>
                  <th>Delivery left</th>
                  <th>Not sent</th>
                  <th>Failed</th>
                  <th>
                    <span className="sr-only">Delivery report</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((entry) => (
                  <tr key={entry.id}>
                    <td className="max-w-md">
                      <p className="font-medium text-slate-900">
                        {entry.version_number === null
                          ? "Legacy record"
                          : `Version ${entry.version_number}`}
                      </p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                        {entry.message_preview || "Saved message"}
                      </p>
                    </td>
                    <td className="whitespace-nowrap text-xs text-slate-500">
                      {workspaceDate(entry.created_at)}
                    </td>
                    <td>{entry.counts.all.toLocaleString()}</td>
                    <td className="text-emerald-700">
                      {entry.counts.sent.toLocaleString()}
                    </td>
                    <td>{entry.counts.delivery_left.toLocaleString()}</td>
                    <td>{entry.counts.not_sent.toLocaleString()}</td>
                    <td
                      className={
                        entry.counts.failed ? "text-red-600" : "text-slate-400"
                      }
                    >
                      {entry.counts.failed.toLocaleString()}
                    </td>
                    <td>
                      <Link
                        aria-label={`View delivery for ${entry.version_number === null ? "legacy record" : `version ${entry.version_number}`}`}
                        href={`${ROUTES.dashboard.whatsappBroadcastHistory(group.id)}?message=${encodeURIComponent(entry.id)}`}
                        className="inline-flex items-center gap-2 whitespace-nowrap text-xs font-medium text-blue-700"
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
          <WorkspacePagination
            total={query.data.total}
            offset={offset}
            limit={25}
            onChange={setOffset}
            label="Message versions"
          />
        </>
      )}
    </section>
  );
}
