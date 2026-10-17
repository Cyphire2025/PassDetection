"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui";
import {
  DialogFrame,
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import { formatMessageType } from "../utils/message-types";
import {
  historyApi,
  type HistoryEntry,
  type HistoryRecipient,
} from "./history.api";
import { workspaceDate } from "./workspace-ui";

export function HistoricalResend({
  groupId,
  entry,
  recipient,
  onClose,
}: {
  groupId: string;
  entry: HistoryEntry;
  recipient: HistoryRecipient;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const lock = useRef(false);
  const [requestId] = useState(() => crypto.randomUUID());
  const [submitted, setSubmitted] = useState(false);
  const mutation = useMutation({
    mutationFn: () =>
      historyApi.resend(groupId, entry.message_type, recipient, requestId),
    retry: false,
    onSuccess: () => {
      setSubmitted(true);
      void queryClient.invalidateQueries({
        queryKey: ["whatsapp", "history", groupId],
      });
      void queryClient.invalidateQueries({ queryKey: ["whatsapp", "groups"] });
    },
  });
  return (
    <DialogFrame
      title={`${recipient.status === "failed" ? "Retry" : "Resend"} this message`}
      description={`Only ${recipient.name || "this recipient"} will receive this message.`}
      onClose={onClose}
      isBusy={mutation.isPending}
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          To <strong>{recipient.current_phone_number}</strong>
          <span className="ml-2 text-xs text-slate-400">
            {formatMessageType(entry.message_type)} ·{" "}
            {workspaceDate(entry.created_at)}
          </span>
        </p>
        <div className="max-h-80 overflow-y-auto rounded-xl bg-emerald-50 p-5 text-sm leading-6 text-slate-800 whitespace-pre-wrap">
          {recipient.rendered_message || entry.message_preview}
        </div>
        {mutation.error && (
          <ErrorBanner
            message={readErrorMessage(
              mutation.error,
              "Could not submit this resend. Refresh delivery status before trying again.",
            )}
          />
        )}
        {submitted && (
          <p role="status" className="text-sm text-emerald-700">
            Send request recorded. Track its current status in Delivery history.
          </p>
        )}
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
          <Button
            variant="secondary"
            onClick={onClose}
            disabled={mutation.isPending}
          >
            {submitted ? "Done" : "Cancel"}
          </Button>
          {!submitted && (
            <Button
              isLoading={mutation.isPending}
              onClick={async () => {
                if (lock.current) return;
                lock.current = true;
                try {
                  await mutation.mutateAsync();
                } catch {
                  /* prevent blind resubmission after an uncertain response */
                } finally {
                  lock.current = false;
                }
              }}
            >
              {mutation.error
                ? "Check resend status"
                : "Send to this recipient"}
            </Button>
          )}
        </div>
      </div>
    </DialogFrame>
  );
}
