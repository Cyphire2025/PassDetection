"use client";

import { ArrowLeft, ArrowRight, RefreshCw, Send } from "lucide-react";
import { useDeferredValue, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { documentDistributionApi } from "@/features/documents/api/document-distribution.api";
import { distributionDocumentLabel } from "@/features/documents/config/document-distribution-lanes";
import {
  DialogFrame,
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { useWhatsAppActivityTracker } from "../components/whatsapp-activity-tracker";
import { useBroadcast } from "./broadcast-workspace-shell";
import { ComposerPreview, ComposerTextField } from "./composer-primitives";
import {
  DeliveryBadge,
  EmptyWorkspace,
  fieldClass,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function BroadcastDocumentComposer({
  documentType,
  sources,
  documentId,
  onClose,
}: {
  documentType: DistributionDocumentType;
  sources: { id: string; name: string }[];
  documentId?: string;
  onClose: () => void;
}) {
  const group = useBroadcast(),
    queryClient = useQueryClient();
  const { registerActivity } = useWhatsAppActivityTracker();
  const queries = useQueries({
    queries: sources.map((source) => ({
      queryKey: [
        "document-distribution",
        "delivery-preview",
        source.id,
        documentType,
        group.id,
      ],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        documentDistributionApi.previewWhatsAppDelivery(
          source.id,
          documentType,
          signal,
        ),
      staleTime: 0,
    })),
  });
  const [content1, setContent1] = useState<string | null>(null),
    [content2, setContent2] = useState<string | null>(null);
  const [selection, setSelection] = useState<string[] | null>(
    documentId ? [documentId] : null,
  );
  const [sampleId, setSampleId] = useState<string | null>(null);
  const [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0);
  const q = useDeferredValue(search).trim().toLocaleLowerCase();
  const [reviewing, setReviewing] = useState(false),
    [pending, setPending] = useState(false),
    [error, setError] = useState<string | null>(null);
  const lock = useRef(false),
    acknowledged = useRef(new Set<string>());
  const previews = queries.flatMap((query) => (query.data ? [query.data] : []));
  const rows = previews.flatMap((preview) =>
    preview.recipients
      .filter((row) => row.document_id && row.broadcast_group_id === group.id)
      .map((row) => ({ row, preview })),
  );
  const selectedIds = new Set(
    selection ??
      rows.filter(({ row }) => row.eligible).map(({ row }) => row.document_id!),
  );
  const selected = rows.filter(
    ({ row }) =>
      row.document_id &&
      selectedIds.has(row.document_id) &&
      (row.eligible || row.resend_allowed),
  );
  const sample =
    rows.find(({ row }) => row.document_id === sampleId) ??
    selected[0] ??
    rows[0];
  const text1 = content1 ?? previews[0]?.message_content_1 ?? "",
    text2 = content2 ?? previews[0]?.message_content_2 ?? "";
  const rendered = previews.length
    ? [
        "Dear Delegates",
        "Greetings from Global Connect Travels",
        text1.trim(),
        text2.trim(),
        "Regards,\nTeam Global Connect Travels",
      ].join("\n\n")
    : null;
  const loading = queries.some((query) => query.isLoading),
    refreshing = queries.some((query) => query.isFetching);
  const loadError = queries.find((query) => query.error)?.error;
  const ready =
    !group.is_archived &&
    !pending &&
    !refreshing &&
    !loadError &&
    queries.length === previews.length &&
    selected.length > 0 &&
    text1.trim().length > 0 &&
    text2.trim().length > 0 &&
    text1.trim().length <= 600 &&
    text2.trim().length <= 600 &&
    previews.every(
      (preview) => preview.template_configured && preview.preview_token,
    );
  const matches = rows.filter(
    ({ row }) =>
      !q ||
      `${row.passenger_name} ${row.phone_number ?? ""} ${row.document_filename ?? ""}`
        .toLocaleLowerCase()
        .includes(q),
  );
  const send = async (startedAt: number) => {
    if (lock.current || !ready) return;
    lock.current = true;
    setPending(true);
    setError(null);
    try {
      for (const preview of previews) {
        if (acknowledged.current.has(preview.batch_id)) continue;
        const included = selected.filter(
          (entry) => entry.preview.batch_id === preview.batch_id,
        );
        if (!included.length) continue;
        const result = await documentDistributionApi.sendWhatsAppDelivery(
          preview.batch_id,
          [...new Set(included.map(({ row }) => row.document_id!))],
          [
            ...new Set(
              included
                .filter(({ row }) => row.delivery_status === "already_sent")
                .map(({ row }) => row.document_id!),
            ),
          ],
          text1.trim(),
          text2.trim(),
          preview.preview_token!,
        );
        acknowledged.current.add(preview.batch_id);
        if (result.send_batch_id)
          registerActivity({
            id: result.send_batch_id,
            kind: "document",
            title: `${distributionDocumentLabel(documentType)} documents`,
            contextLabel: group.name,
            sourceGroupId: preview.group_id,
            documentType,
            startedAt,
            total: result.queued_count,
            queued: result.queued_count,
            sent: 0,
            failed: 0,
            deliveryUnknown: 0,
          });
      }
      void queryClient.invalidateQueries({
        queryKey: ["document-distribution"],
      });
      onClose();
    } catch (cause) {
      setError(
        readErrorMessage(
          cause,
          "Document delivery was not fully confirmed. Refresh delivery status before trying again.",
        ),
      );
    } finally {
      lock.current = false;
      setPending(false);
    }
  };
  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" disabled={pending} onClick={onClose}>
        <ArrowLeft className="h-3.5 w-3.5" />
        Passenger documents
      </Button>
      <div>
        <h2 className="text-lg font-semibold text-slate-900">
          Send {distributionDocumentLabel(documentType).toLocaleLowerCase()}{" "}
          documents
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Write the message first, then review each passenger’s PDF and
          destination.
        </p>
      </div>
      {loadError && (
        <ErrorBanner
          message={readErrorMessage(
            loadError,
            "The document preview could not be loaded.",
          )}
        />
      )}
      <section className={`${styles.surface} p-5 sm:p-6`}>
        <div className="grid items-start gap-7 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          <fieldset
            disabled={pending || loading || group.is_archived}
            className="min-w-0 space-y-5"
          >
            <h3 className="border-b border-slate-100 pb-3 text-sm font-semibold text-slate-900">
              Write your message
            </h3>
            <ComposerTextField
              label="Document message"
              value={text1}
              onChange={setContent1}
            />
            <ComposerTextField
              label="Review instructions"
              value={text2}
              onChange={setContent2}
            />
          </fieldset>
          <aside className="min-w-0 lg:sticky lg:top-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-900">
              WhatsApp preview
            </h3>
            <ComposerPreview
              message={rendered}
              current={!refreshing && !loadError}
              recipientName={sample?.row.passenger_name}
              attachment={sample?.row.document_filename}
            >
              <label className="block text-xs font-medium text-slate-500">
                Preview for
                <select
                  className={`mt-1.5 ${fieldClass}`}
                  value={sample?.row.document_id ?? ""}
                  onChange={(event) => setSampleId(event.target.value)}
                >
                  {rows.map(({ row }) => (
                    <option
                      key={`${row.passenger_id}:${row.document_id}`}
                      value={row.document_id ?? ""}
                    >
                      {row.passenger_name} · {row.document_filename}
                    </option>
                  ))}
                </select>
              </label>
            </ComposerPreview>
          </aside>
        </div>
      </section>
      <section className={styles.surface}>
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-slate-900">
              Recipients for this send
            </h3>
            <span className="text-xs text-slate-500">
              {selected.length} document messages selected
            </span>
          </div>
          <WorkspaceSearch
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            label="Search document recipients"
            placeholder="Search passenger, number or PDF…"
          >
            <Button
              variant="ghost"
              disabled={pending}
              onClick={() => {
                setError(null);
                for (const query of queries) void query.refetch();
              }}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh status
            </Button>
          </WorkspaceSearch>
        </div>
        {loading ? (
          <Skeleton className="m-5 h-48" />
        ) : !matches.length ? (
          <EmptyWorkspace
            title="No matching document recipients"
            description="Only passengers with assigned PDFs linked to this broadcast appear here."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th>
                    <span className="sr-only">Select</span>
                  </th>
                  <th>Passenger and PDF</th>
                  <th>WhatsApp number</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {matches.slice(offset, offset + 25).map(({ row }) => (
                  <tr key={`${row.passenger_id}:${row.document_id}`}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Select document for ${row.passenger_name}`}
                        className="h-4 w-4 accent-blue-600"
                        disabled={
                          pending || (!row.eligible && !row.resend_allowed)
                        }
                        checked={Boolean(
                          row.document_id && selectedIds.has(row.document_id),
                        )}
                        onChange={(event) => {
                          const next = new Set(selectedIds);
                          if (event.target.checked) next.add(row.document_id!);
                          else next.delete(row.document_id!);
                          setSelection([...next]);
                        }}
                      />
                    </td>
                    <td>
                      <p className="font-medium text-slate-800">
                        {row.passenger_name}
                      </p>
                      <p className="mt-1 max-w-sm break-words text-xs text-slate-400">
                        {row.document_filename}
                      </p>
                    </td>
                    <td className="tabular-nums text-slate-500">
                      {row.phone_number || "Missing number"}
                    </td>
                    <td>
                      <DeliveryBadge
                        status={
                          row.delivery_status === "already_sent"
                            ? "sent"
                            : row.delivery_status === "ready"
                              ? "not_sent"
                              : row.delivery_status
                        }
                      />
                      <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">
                        {row.delivery_status === "already_sent"
                          ? "Previously sent · select to resend"
                          : row.reason}
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <WorkspacePagination
          total={matches.length}
          offset={offset}
          limit={25}
          onChange={setOffset}
          label="Document recipients"
          busy={pending}
        />
      </section>
      <div className="sticky bottom-0 z-10 flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white/95 px-5 py-4 shadow-sm">
        <span className="text-xs text-slate-500">
          {selected.length} document messages selected
        </span>
        <Button disabled={!ready} onClick={() => setReviewing(true)}>
          Review message
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
      {reviewing && (
        <DialogFrame
          title="Review document delivery"
          onClose={() => setReviewing(false)}
          isBusy={pending}
        >
          <div className="space-y-4">
            <p className="text-sm text-slate-700">
              {selected.length} individual document messages will be sent,
              including{" "}
              {
                selected.filter(
                  ({ row }) => row.delivery_status === "already_sent",
                ).length
              }{" "}
              explicit resends.
            </p>
            <p className="whitespace-pre-wrap rounded-xl bg-emerald-50 p-4 text-sm leading-6 text-slate-800">
              {rendered}
            </p>
            {error && <ErrorBanner message={error} />}
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                disabled={pending}
                onClick={() => setReviewing(false)}
              >
                Back to editing
              </Button>
              <Button
                disabled={!ready || Boolean(error)}
                isLoading={pending}
                onClick={() => void send(Date.now())}
              >
                <Send className="h-4 w-4" />
                Send {selected.length} messages
              </Button>
            </div>
          </div>
        </DialogFrame>
      )}
    </div>
  );
}
