import { useEffect, useRef, useState } from "react";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import { exportWhatsAppExcel, type WhatsAppExportRequest } from "../api/whatsapp-export.api";

type ExportState = { groupId: string; pending: boolean; error: unknown };

export function useWhatsAppExport(groupId: string, groupName: string) {
  const active = useRef<{ groupId: string; controller: AbortController } | null>(null);
  const [state, setState] = useState<ExportState | null>(null);

  useEffect(() => () => {
    if (active.current?.groupId === groupId) {
      active.current.controller.abort();
      active.current = null;
    }
  }, [groupId]);

  const exportExcel = async (buildRequest: () => WhatsAppExportRequest) => {
    if (active.current) return;
    const operation = { groupId, controller: new AbortController() };
    active.current = operation;
    setState({ groupId, pending: true, error: null });
    try {
      // Capture the matching rows before the Save As dialog or network awaits.
      const request = buildRequest();
      if (request.items.length === 0) return;
      await exportWhatsAppExcel(groupId, groupName, request, operation.controller.signal);
    } catch (error) {
      if (active.current === operation && !operation.controller.signal.aborted && !isDownloadCancelled(error)) {
        setState({ groupId, pending: false, error });
      }
    } finally {
      if (active.current === operation) {
        active.current = null;
        setState((current) => current?.groupId === groupId ? { ...current, pending: false } : current);
      }
    }
  };

  return {
    exportExcel,
    isPending: state?.groupId === groupId && state.pending,
    error: state?.groupId === groupId ? state.error : null,
  };
}
