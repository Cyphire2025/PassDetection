"use client";

import { ROUTES } from "@/constants/routes";
import { ArrowUpRight, FileText, RefreshCw, Send } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { documentDistributionApi } from "@/features/documents/api/document-distribution.api";
import { distributionDocumentLabel } from "@/features/documents/config/document-distribution-lanes";
import { reviewRowDocuments } from "@/features/documents/components/document-workspace-model";
import {
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { useBroadcast } from "./broadcast-workspace-shell";
import { BroadcastDocumentComposer } from "./document-composer";
import { composerApi } from "./composer.api";
import {
  DeliveryBadge,
  EmptyWorkspace,
  fieldClass,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

const documentTypes: DistributionDocumentType[] = [
  "visa",
  "flight_ticket",
  "flight_ticket_arrival",
  "flight_ticket_domestic",
  "flight_ticket_domestic_arrival",
];
const filters = [
  ["all", "All"],
  ["multiple", "Multiple PDFs"],
  ["shared", "Shared PDF"],
  ["assigned", "Assigned"],
  ["missing", "Missing"],
  ["sent", "Sent"],
  ["not_sent", "Not sent"],
] as const;
const accepted = new Set(["submitted", "sent", "delivered", "read"]);

export function BroadcastDocumentsPage() {
  const group = useBroadcast();
  const [documentType, setDocumentType] =
    useState<DistributionDocumentType>("visa");
  const [filter, setFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search).trim().toLocaleLowerCase();
  const [offset, setOffset] = useState(0);
  const [composing, setComposing] = useState<{ documentId?: string } | null>(
    null,
  );
  const linked = group.linked_client_groups ?? [];
  const passengerLinks = useQuery({
    queryKey: ["whatsapp", "passenger-links", group.id],
    queryFn: ({ signal }) => composerApi.passengerLinks(group.id, signal),
    enabled: linked.length > 0,
    refetchInterval: 20_000,
  });
  const queries = useQueries({
    queries: linked.map((source) => ({
      queryKey: [
        "document-distribution",
        "broadcast-review",
        group.id,
        source.id,
        documentType,
      ],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        documentDistributionApi.getReview(source.id, documentType, signal),
      refetchInterval: 20_000,
    })),
  });
  const allEntries = queries.flatMap(
    (query, index) =>
      query.data?.review_rows.map((row) => ({
        row,
        source: linked[index],
        documents: reviewRowDocuments(row),
      })) ?? [],
  );
  const linkedPassengers = new Set(
    passengerLinks.data?.map((link) => `${link.group_id}:${link.passenger_id}`),
  );
  const entries = allEntries.filter((entry) =>
    linkedPassengers.has(`${entry.source.id}:${entry.row.passenger_id}`),
  );
  const documentIdentity = (
    entry: (typeof allEntries)[number],
    document: (typeof entry.documents)[number],
  ) => `${entry.source.id}:${document.url?.split("?")[0] ?? document.id}`;
  const sharedUrls = new Map<string, Set<string>>();
  for (const entry of allEntries)
    for (const document of entry.documents) {
      const identity = documentIdentity(entry, document);
      const people = sharedUrls.get(identity) ?? new Set<string>();
      people.add(entry.row.passenger_id);
      sharedUrls.set(identity, people);
    }
  const isShared = (entry: (typeof entries)[number]) =>
    entry.documents.some(
      (document) =>
        (sharedUrls.get(documentIdentity(entry, document))?.size ?? 0) > 1,
    );
  const matchesFilter = (entry: (typeof entries)[number], value: string) => {
    const sent =
      entry.documents.length > 0 &&
      entry.documents.every((document) =>
        accepted.has(document.delivery_status),
      );
    if (value === "multiple")
      return (entry.row.assigned_pdf_count ?? entry.documents.length) > 1;
    if (value === "shared") return isShared(entry);
    if (value === "assigned") return entry.documents.length > 0;
    if (value === "missing") return entry.documents.length === 0;
    if (value === "sent") return sent;
    if (value === "not_sent") return entry.documents.length > 0 && !sent;
    return true;
  };
  const displayed = entries.filter(
    (entry) =>
      matchesFilter(entry, filter) &&
      (!q ||
        `${entry.row.passenger_name} ${entry.row.passport_number ?? ""}`
          .toLocaleLowerCase()
          .includes(q)),
  );
  const loading =
      passengerLinks.isLoading || queries.some((query) => query.isLoading),
    error = passengerLinks.error ?? queries.find((query) => query.error)?.error;
  const refreshing = queries.some((query) => query.isFetching);
  const sources = linked.map((source) => ({
    id: source.id,
    name: source.name,
  }));
  const pageOffset = Math.min(
    offset,
    Math.max(0, Math.ceil(displayed.length / 50) - 1) * 50,
  );
  if (composing)
    return (
      <BroadcastDocumentComposer
        documentType={documentType}
        sources={sources}
        documentId={composing.documentId}
        onClose={() => setComposing(null)}
      />
    );
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            Passenger documents
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Assigned documents and delivery for this broadcast’s linked
            passengers.
          </p>
        </div>
        <Button
          disabled={
            group.is_archived ||
            !entries.some((entry) => entry.documents.length > 0)
          }
          onClick={() => setComposing({})}
        >
          <Send className="h-4 w-4" />
          Send documents
        </Button>
      </div>
      {!linked.length ? (
        <section className={styles.surface}>
          <EmptyWorkspace
            title="No linked documents yet"
            description="Documents appear here once this broadcast is linked to a trip group."
          />
        </section>
      ) : (
        <section className={styles.surface}>
          <div className="space-y-4 p-5">
            <WorkspaceSearch
              value={search}
              onChange={(value) => {
                setSearch(value);
                setOffset(0);
              }}
              label="Search passenger documents"
              placeholder="Search passenger name or passport…"
            >
              <label className="text-xs text-slate-500">
                <span className="sr-only">Document type</span>
                <select
                  aria-label="Document type"
                  value={documentType}
                  onChange={(event) => {
                    setDocumentType(
                      event.target.value as DistributionDocumentType,
                    );
                    setOffset(0);
                  }}
                  className={`${fieldClass} w-auto`}
                >
                  {documentTypes.map((value) => (
                    <option key={value} value={value}>
                      {distributionDocumentLabel(value)}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                variant="ghost"
                isLoading={refreshing && !loading}
                onClick={() => {
                  void passengerLinks.refetch();
                  for (const query of queries) void query.refetch();
                }}
                aria-label="Refresh documents"
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </WorkspaceSearch>
            <div className="flex flex-wrap gap-2">
              {filters.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={filter === value}
                  aria-label={`${label} (${loading ? "loading" : entries.filter((entry) => matchesFilter(entry, value)).length})`}
                  onClick={() => {
                    setFilter(value);
                    setOffset(0);
                  }}
                  className={`rounded-lg px-3 py-2 text-xs font-medium ${filter === value ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
                >
                  {label}
                  <span className="ml-2 tabular-nums opacity-70">
                    {loading
                      ? "—"
                      : entries.filter((entry) => matchesFilter(entry, value))
                          .length}
                  </span>
                </button>
              ))}
            </div>
          </div>
          {loading ? (
            <Skeleton className="m-5 h-64" />
          ) : error ? (
            <div className="p-5">
              <ErrorBanner
                message={readErrorMessage(
                  error,
                  "Passenger documents could not be loaded.",
                )}
              />
            </div>
          ) : !displayed.length ? (
            <EmptyWorkspace
              title="No matching passenger documents"
              description="Choose another document type, change the filter or clear your search."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th>Passenger</th>
                    <th>Passport</th>
                    <th>Documents</th>
                    <th>Delivery</th>
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {displayed
                    .slice(pageOffset, pageOffset + 50)
                    .map(({ row, source, documents }) => (
                      <tr key={`${source.id}:${row.passenger_id}`}>
                        <td>
                          <p className="font-medium text-slate-900">
                            {row.passenger_name}
                          </p>
                          {linked.length > 1 && (
                            <p className="mt-1 text-xs text-slate-400">
                              {source.name}
                            </p>
                          )}
                        </td>
                        <td className="text-slate-500">
                          {row.passport_number || "—"}
                        </td>
                        <td className="min-w-56 max-w-sm">
                          {documents.length ? (
                            <div className="space-y-3">
                              {documents.map((document) => (
                                <div key={document.id}>
                                  {document.url ? (
                                    <a
                                      href={document.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="inline-flex items-start gap-2 text-xs font-medium text-blue-700 hover:underline"
                                    >
                                      <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                      <span className="break-words">
                                        {document.original_filename}
                                      </span>
                                    </a>
                                  ) : (
                                    <span className="text-xs text-slate-600">
                                      {document.original_filename}
                                    </span>
                                  )}
                                  <p className="mt-1 text-[11px] text-slate-400">
                                    {document.source === "manual"
                                      ? "Uploaded"
                                      : "From email"}{" "}
                                    ·{" "}
                                    {Math.round(
                                      document.match_confidence *
                                        (document.match_confidence <= 1
                                          ? 100
                                          : 1),
                                    )}
                                    % match
                                  </p>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <span className="text-xs text-amber-700">
                              Document missing
                            </span>
                          )}
                        </td>
                        <td>
                          {documents.length ? (
                            <div className="space-y-2">
                              {documents.map((document) => (
                                <div key={document.id}>
                                  <DeliveryBadge
                                    status={document.delivery_status}
                                  />
                                  {document.sent_to && (
                                    <p className="mt-1 text-[11px] text-slate-400">
                                      {document.sent_to}
                                    </p>
                                  )}
                                </div>
                              ))}
                            </div>
                          ) : (
                            <span className="text-slate-300">—</span>
                          )}
                        </td>
                        <td>
                          {documents
                            .filter((document) => document.can_resend)
                            .map((document) => (
                              <Button
                                key={document.id}
                                size="sm"
                                variant="ghost"
                                disabled={group.is_archived}
                                onClick={() =>
                                  setComposing({ documentId: document.id })
                                }
                              >
                                Resend{documents.length > 1 ? " PDF" : ""}
                              </Button>
                            ))}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
          <WorkspacePagination
            total={displayed.length}
            offset={pageOffset}
            limit={50}
            onChange={setOffset}
            label="Passenger documents"
          />
          <div className="flex flex-wrap gap-3 border-t border-slate-100 px-5 py-3">
            {linked.map((source) => (
              <Link
                key={source.id}
                href={ROUTES.dashboard.documentGroup(source.id)}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-700"
              >
                Manage{" "}
                {linked.length > 1 ? source.name : "document assignments"}
                <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
