"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import type { AuditLogListItem } from "@/features/operations/api/operations.api";
import { useAuditLogExport, useAuditLogPages } from "@/features/operations/hooks/use-operations";
import { EMPTY_FILTERS, toApiFilters, type AuditFilterState } from "../audit-filter-model";

export function useAuditLedger() {
  const role = useAuthStore(selectUserRole);
  const sessionVersion = useAuthStore((state) => state.sessionVersion);
  const [filters, setFilters] = useState<AuditFilterState>(EMPTY_FILTERS);
  const deferredFilters = useDeferredValue(filters);
  const apiFilters = useMemo(
    () => toApiFilters(deferredFilters, role === "super_admin"),
    [deferredFilters, role],
  );
  const auditQuery = useAuditLogPages(apiFilters);
  const exportMutation = useAuditLogExport();
  const exportControllerRef = useRef<AbortController | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const auditPages = auditQuery.data?.pages;
  const data = useMemo(() => {
    const byId = new Map<string, AuditLogListItem>();
    for (const page of auditPages ?? []) {
      for (const item of page.items) byId.set(item.id, item);
    }
    return Array.from(byId.values());
  }, [auditPages]);
  const actors = useMemo(
    () => new Set(data.flatMap((log) => (log.actor_email ? [log.actor_email] : []))),
    [data],
  );
  const systemEvents = useMemo(
    () => data.filter((log) => !log.actor_email).length,
    [data],
  );
  const latestEvent = data[0] ?? null;
  const isFiltered = Object.values(filters).some(Boolean);
  const hasMore = auditQuery.hasNextPage === true;
  const latestPage = auditPages && auditPages.length > 0
    ? auditPages[auditPages.length - 1]
    : null;
  const isIncomplete = latestPage?.incomplete === true;
  const hasBrokenContinuation = isIncomplete && latestPage?.has_more === true && !latestPage.next_cursor;
  const canExport = Boolean(apiFilters.start_at && apiFilters.end_at);

  useEffect(() => () => {
    exportControllerRef.current?.abort();
    exportControllerRef.current = null;
  }, [sessionVersion]);

  const updateFilter = <Field extends keyof AuditFilterState>(
    field: Field,
    value: AuditFilterState[Field],
  ) => {
    setFilters((current) => ({ ...current, [field]: value }));
  };

  const exportLedger = async () => {
    const startAt = apiFilters.start_at;
    const endAt = apiFilters.end_at;
    if (!startAt || !endAt || exportMutation.isPending) return;
    setExportNotice(null);
    exportControllerRef.current?.abort();
    const controller = new AbortController();
    exportControllerRef.current = controller;
    try {
      const exported = await exportMutation.mutateAsync({
        filters: {
          ...apiFilters,
          start_at: startAt,
          end_at: endAt,
        },
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setExportNotice(exported.truncated
        ? "The export reached the 10,000-row safety limit. Narrow the time range for complete evidence."
        : "The audit export is ready.");
    } catch (error) {
      if (controller.signal.aborted || isDownloadCancelled(error)) return;
      setExportNotice("The audit export could not be prepared. Please try again.");
    } finally {
      if (exportControllerRef.current === controller) {
        exportControllerRef.current = null;
      }
    }
  };

  return {
    role, filters, setFilters, auditQuery, exportMutation, exportNotice,
    data, actors, systemEvents, latestEvent, isFiltered, hasMore, isIncomplete,
    hasBrokenContinuation, canExport, updateFilter, exportLedger
  };
}

export type AuditLedgerController = ReturnType<typeof useAuditLedger>;
