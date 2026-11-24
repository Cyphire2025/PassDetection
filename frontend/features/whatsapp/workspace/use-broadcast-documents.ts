"use client";

import { useDeferredValue, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { clampPageOffset } from "@/lib/utils/pagination";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { documentDistributionApi } from "@/features/documents/api/document-distribution.api";
import { reviewRowDocuments } from "@/features/documents/components/document-workspace-model";
import { isTerminalWhatsAppBatchStatus, whatsappBatchHttpStatus } from "../utils/batch-polling";
import { useBroadcast } from "./broadcast-workspace-shell";
import { composerApi } from "./composer.api";
import { buildBroadcastDocumentProjection } from "./broadcast-documents-model";

function broadcastDocumentsPollInterval(query: { state: { error: unknown } }): number | false {
  return isTerminalWhatsAppBatchStatus(whatsappBatchHttpStatus(query.state.error)) ? false : 20_000;
}

export function useBroadcastDocuments() {
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
    refetchInterval: broadcastDocumentsPollInterval,
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
      refetchInterval: broadcastDocumentsPollInterval,
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
  const { entries, displayed, counts } = buildBroadcastDocumentProjection(allEntries, passengerLinks.data, filter, q);
  const loading =
    passengerLinks.isLoading || queries.some((query) => query.isLoading),
    error = passengerLinks.error ?? queries.find((query) => query.error)?.error;
  const refreshing = passengerLinks.isFetching || queries.some((query) => query.isFetching);
  const sources = linked.map((source) => ({
    id: source.id,
    name: source.name,
  }));
  const pageOffset = clampPageOffset(offset, displayed.length, 50);
  return {
    group,
    documentType,
    setDocumentType,
    filter,
    setFilter,
    search,
    setSearch,
    setOffset,
    composing,
    setComposing,
    linked,
    passengerLinks,
    queries,
    entries,
    displayed,
    counts,
    loading,
    error,
    refreshing,
    sources,
    pageOffset
  };
}

export type BroadcastDocumentsController = ReturnType<typeof useBroadcastDocuments>;
