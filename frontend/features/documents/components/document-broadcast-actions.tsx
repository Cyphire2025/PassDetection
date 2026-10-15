"use client";

import { useId, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { FileText, MessageSquare, Send, X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { DistributionDocumentType } from "@/types/document-distribution.types";

const UpdateDialog = dynamic(() => import("./document-update-dialog").then(module => module.DocumentUpdateDialog));

export function DocumentBroadcastActions({ groupId, documentType, broadcastGroupId, onSendDocuments, documentsDisabled = false }: {
  groupId: string;
  documentType: DistributionDocumentType;
  broadcastGroupId?: string;
  onSendDocuments: () => void;
  documentsDisabled?: boolean;
}) {
  const [mode, setMode] = useState<"choose" | "update" | null>(null);
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: mode === "choose", canClose: true, onClose: () => setMode(null) });
  return <>
    <Button variant="secondary" onClick={() => setMode("choose")}><Send className="h-4 w-4" />Send WhatsApp Broadcast</Button>
    {mode === "choose" ? <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-900/50 p-4">
      <div ref={dialogRef} onKeyDown={handleKeyDown} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between gap-4"><h2 id={titleId} className="text-xl font-semibold">Send WhatsApp broadcast</h2><button type="button" aria-label="Close broadcast options" onClick={() => setMode(null)}><X className="h-5 w-5" /></button></div>
        <p className="mt-2 text-sm text-slate-600">Choose what you want to send, then review the recipients.</p>
        <div className="mt-5 grid gap-3">
          <Button variant="secondary" data-dialog-initial-focus disabled={documentsDisabled} onClick={() => { setMode(null); onSendDocuments(); }}><FileText className="h-5 w-5" />Send documents</Button>
          <p className="text-sm text-slate-600">Send each traveller their assigned PDF.</p>
          <Button variant="secondary" onClick={() => setMode("update")}><MessageSquare className="h-5 w-5" />Inform / update</Button>
          <p className="text-sm text-slate-600">Send a message to travellers still waiting for a confirmed document send.</p>
        </div>
      </div>
    </div> : null}
    {mode === "update" ? <UpdateDialog groupId={groupId} documentType={documentType} broadcastGroupId={broadcastGroupId} onClose={() => setMode(null)} /> : null}
  </>;
}
