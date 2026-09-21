"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui";
import type { WhatsAppBroadcastGroup, WhatsAppMessageType } from "../api/whatsapp.api";
import type { WhatsAppExportItem, WhatsAppExportRequest } from "../api/whatsapp-export.api";
import { useWhatsAppExport } from "../hooks/use-whatsapp-export";
import { readErrorMessage } from "./whatsapp-dialog-ui";

interface WhatsAppExportButtonProps {
  group: Pick<WhatsAppBroadcastGroup, "id" | "name">;
  view: WhatsAppExportRequest["view"];
  filterLabel: string;
  messageType?: WhatsAppMessageType;
  count: number;
  getItems: () => WhatsAppExportItem[];
  disabled?: boolean;
}

export function WhatsAppExportButton({
  group,
  view,
  filterLabel,
  messageType,
  count,
  getItems,
  disabled = false,
}: WhatsAppExportButtonProps) {
  const download = useWhatsAppExport(group.id, group.name);
  return (
    <div className="flex flex-col items-start gap-2 sm:items-end">
      <Button
        type="button"
        variant="secondary"
        size="sm"
        isLoading={download.isPending}
        disabled={disabled || count === 0}
        title={`Export all ${count.toLocaleString()} matching rows across every page`}
        onClick={() => {
          if (disabled || count === 0) return;
          void download.exportExcel(() => ({
            view,
            items: getItems(),
            filter_label: filterLabel.slice(0, 80),
            ...(messageType ? { message_type: messageType } : {}),
          }));
        }}
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        Export Excel
      </Button>
      {Boolean(download.error) && (
        <p role="alert" className="max-w-sm text-xs leading-5 text-red-700">
          {readErrorMessage(download.error, "Could not export these rows. Refresh the list and try again.")}
        </p>
      )}
    </div>
  );
}
