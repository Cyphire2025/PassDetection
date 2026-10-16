"use client";

import { ArrowLeft, ArrowRight, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { formatMessageType } from "../utils/message-types";
import { useBroadcast } from "./broadcast-workspace-shell";
import { historyApi } from "./history.api";
import { TypeRecipientReport } from "./message-type-recipients";
import { MessageTypeVersions } from "./message-type-versions";
import { tableClass, workspaceDate } from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function MessageTypeOverview({
  messageType,
  versions = false,
}: {
  messageType: string | null;
  versions?: boolean;
}) {
  const group = useBroadcast();
  const base = ROUTES.dashboard.whatsappBroadcastHistory(group.id);
  const query = useQuery({
    queryKey: ["whatsapp", "history", group.id, "types"],
    queryFn: ({ signal }) => historyApi.types(group.id, signal),
    refetchInterval: 15_000,
  });
  const summary = query.data?.find((item) => item.message_type === messageType);
  return (
    <div className="space-y-5">
      {messageType && (
        <Link
          href={`${base}?view=types`}
          className="inline-flex items-center gap-2 text-xs font-medium text-slate-500 hover:text-blue-700"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          All message types
        </Link>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            {messageType
              ? formatMessageType(messageType)
              : "Delivery by message type"}
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
            Overall totals count each current recipient once. Sent means at
            least one version was accepted by WhatsApp; repeating a message does
            not count that person twice.
          </p>
        </div>
        <Button
          variant="ghost"
          isLoading={query.isFetching && !query.isLoading}
          onClick={() => void query.refetch()}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh totals
        </Button>
      </div>
      {query.isLoading ? (
        <Skeleton className="h-64" />
      ) : query.error ? (
        <ErrorBanner
          message={readErrorMessage(
            query.error,
            "Delivery totals could not be loaded.",
          )}
        />
      ) : messageType && summary ? (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: "Sent at least once", value: summary.counts.sent },
              { label: "Not sent", value: summary.counts.not_sent },
              { label: "Failed / unconfirmed", value: summary.counts.failed },
              { label: "Recorded sends", value: summary.send_count },
            ].map((item) => (
              <div key={item.label} className={`${styles.surface} p-4`}>
                <p className="text-xs text-slate-500">{item.label}</p>
                <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">
                  {item.value.toLocaleString()}
                </p>
              </div>
            ))}
          </div>
          <div
            className="flex flex-wrap items-center gap-2 border-b border-slate-200 pb-3"
            aria-label="Message type reports"
          >
            <Link
              aria-current={!versions ? "page" : undefined}
              href={{
                pathname: base,
                query: { view: "types", type: messageType },
              }}
              className={`rounded-lg px-4 py-2 text-sm font-medium ${!versions ? "bg-blue-50 text-blue-700" : "text-slate-500 hover:bg-white"}`}
            >
              Overall recipients
            </Link>
            <Link
              aria-current={versions ? "page" : undefined}
              href={{
                pathname: base,
                query: { view: "types", type: messageType, report: "versions" },
              }}
              className={`rounded-lg px-4 py-2 text-sm font-medium ${versions ? "bg-blue-50 text-blue-700" : "text-slate-500 hover:bg-white"}`}
            >
              Versions ({summary.version_count.toLocaleString()})
            </Link>
            <span className="ml-auto text-xs text-slate-500">
              {summary.counts.all.toLocaleString()} current recipients ·{" "}
              {summary.never_attempted.toLocaleString()} never attempted
            </span>
          </div>
          {versions ? (
            <MessageTypeVersions key={messageType} messageType={messageType} />
          ) : (
            <TypeRecipientReport key={messageType} messageType={messageType} />
          )}
        </>
      ) : messageType ? (
        <ErrorBanner message="This message type was not found in this broadcast." />
      ) : (
        <section className={`${styles.surface} overflow-hidden`}>
          <div className="overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th>Message type</th>
                  <th>Sent at least once</th>
                  <th>Not sent</th>
                  <th>Failed</th>
                  <th>Recorded sends</th>
                  <th>Last send</th>
                  <th>
                    <span className="sr-only">Reports</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {query.data?.map((item) => (
                  <tr key={item.message_type}>
                    <td className="font-medium text-slate-900">
                      {formatMessageType(item.message_type)}
                    </td>
                    <td>
                      <span className="font-medium text-emerald-700">
                        {item.counts.sent.toLocaleString()}
                      </span>
                      <span className="text-xs text-slate-400">
                        {" "}
                        / {item.counts.all.toLocaleString()}
                      </span>
                    </td>
                    <td>{item.counts.not_sent.toLocaleString()}</td>
                    <td
                      className={
                        item.counts.failed ? "text-red-600" : "text-slate-400"
                      }
                    >
                      {item.counts.failed.toLocaleString()}
                    </td>
                    <td>{item.send_count.toLocaleString()}</td>
                    <td className="text-xs text-slate-500">
                      {item.last_sent_at
                        ? workspaceDate(item.last_sent_at)
                        : "No sends yet"}
                    </td>
                    <td>
                      <Link
                        aria-label={`View ${formatMessageType(item.message_type)} overall delivery`}
                        href={`${base}?view=types&type=${encodeURIComponent(item.message_type)}`}
                        className="inline-flex items-center gap-2 whitespace-nowrap text-xs font-medium text-blue-700"
                      >
                        View reports
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-slate-100 px-5 py-4 text-xs leading-5 text-slate-500">
            Each new send is listed separately under Versions, even when its
            wording is identical. Version reports retain their original
            audience; overall totals use the current recipient list.
          </p>
        </section>
      )}
    </div>
  );
}
