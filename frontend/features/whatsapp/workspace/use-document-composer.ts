"use client";

import { useDeferredValue, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { clampPageOffset } from "@/lib/utils/pagination";
import { capturePrivateOperationOwner } from "@/lib/api/request-owner";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { documentDistributionApi } from "@/features/documents/api/document-distribution.api";
import { distributionDocumentLabel } from "@/features/documents/config/document-distribution-lanes";
import { readErrorMessage } from "../components/whatsapp-dialog-ui";
import { useWhatsAppActivityTracker } from "../components/whatsapp-activity-tracker";
import { useBroadcast } from "./broadcast-workspace-shell";

export interface DocumentComposerProps {
  documentType: DistributionDocumentType;
  sources: { id: string; name: string }[];
  documentId?: string;
  onClose: () => void;
}

export function useDocumentComposer({ documentType, sources, documentId, onClose }: DocumentComposerProps) {
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
          group.id,
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
      const operation = capturePrivateOperationOwner();
      for (const preview of previews) {
        if (acknowledged.current.has(preview.batch_id)) continue;
        const included = selected.filter(
          (entry) => entry.preview.batch_id === preview.batch_id,
        );
        if (!included.length) continue;
        operation.assertCurrent();
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
          group.id,
        );
        operation.assertCurrent();
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
  const pageOffset = clampPageOffset(offset, matches.length, 25);
  return {
    group, queries, pending, error, loadError,
    loading, refreshing, text1, text2, setContent1,
    setContent2, rendered, sample, rows, setSampleId,
    selected, search, setSearch, setOffset, setError,
    matches, pageOffset, selectedIds, setSelection, ready,
    reviewing, setReviewing, send,
  };
}
