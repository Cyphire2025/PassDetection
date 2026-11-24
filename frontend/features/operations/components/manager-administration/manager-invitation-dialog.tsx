"use client";

import { useId, useRef } from "react";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button, Card, CardContent } from "@/components/ui";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import type { ManagerAccount } from "../../api/operations.api";

export function ManagerInvitationDialog({
  manager,
  onClose,
}: {
  manager: ManagerAccount;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const link = manager.activation_token ? managerActivationLink(manager.activation_token) : "";
  const handleDialogKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: true,
    canClose: true,
    onClose,
  });

  return (
    <div ref={dialogRef} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={handleDialogKeyDown}>
      <Card className="w-full max-w-lg overflow-hidden shadow-2xl">
        <CardContent className="space-y-5 p-6">
          <div>
            <h2 id={titleId} className="text-base font-semibold text-slate-900">Manager invitation created</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              {manager.full_name} must use this single-use link within seven days. The raw link is not stored in the dashboard.
            </p>
          </div>
          <div className="break-all rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-800">{link}</div>
          {copyError && <p role="alert" className="text-sm text-red-700">The link could not be copied. Select the link above and copy it manually.</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={onClose} data-dialog-initial-focus>Done</Button>
            <Button
              type="button"
              leftIcon={copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
              onClick={async () => {
                setCopyError(false);
                try { await copyTextToClipboard(link); setCopied(true); }
                catch { setCopyError(true); }
              }}
            >
              {copied ? "Copied" : "Copy link"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function managerActivationLink(token: string): string {
  if (typeof window === "undefined") return token;
  const url = new URL("/activate", window.location.origin);
  url.searchParams.set("token", token);
  return url.toString();
}

