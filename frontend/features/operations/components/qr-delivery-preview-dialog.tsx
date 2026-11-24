"use client";

import { useRef } from "react";
import { QrCode, Send, X } from "lucide-react";
import { Button, Skeleton } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { QrDeliveryPreview } from "../api/operations.api";
import type { QrImageMap } from "./group-qr-model";
import { QrDeliverySummary, QrDeliveryPreviewStatus } from "./qr-delivery-status";
import { formatQrStatus } from "./qr-status";

export function QrDeliveryPreviewDialog({
  preview,
  loading,
  loadError,
  qrImages,
  selectedQrTokenIds,
  messageContent,
  sending,
  sendError,
  sendFeedback,
  onMessageContentChange,
  onToggleQr,
  onClose,
  onSend,
}: {
  preview: QrDeliveryPreview | undefined;
  loading: boolean;
  loadError: Error | null;
  qrImages: QrImageMap;
  selectedQrTokenIds: string[];
  messageContent: string;
  sending: boolean;
  sendError: Error | null;
  sendFeedback: string | null;
  onMessageContentChange: (value: string) => void;
  onToggleQr: (qrTokenId: string) => void;
  onClose: () => void;
  onSend: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const handleDialogKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !sending, onClose });

  const sampleMessage = [
    "Dear Delegates",
    "Greetings from Global Connect Travels",
    messageContent,
    "Regards,\nTeam Global Connect Travels",
  ].join("\n\n");
  const selectedQrTokenSet = new Set(selectedQrTokenIds);
  const previewPassenger = preview?.recipients.find(
    (recipient) =>
      recipient.qr_token_id && selectedQrTokenSet.has(recipient.qr_token_id),
  );
  const messageContentValid =
    Boolean(messageContent.trim()) && messageContent.length <= 600;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm print:hidden"
      role="dialog"
      aria-modal="true"
      aria-labelledby="qr-delivery-preview-title"
    >
      <div ref={dialogRef} onKeyDown={handleDialogKeyDown} className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
          <div>
            <h2 id="qr-delivery-preview-title" className="text-lg font-semibold text-slate-950">
              Preview WhatsApp QR delivery
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Confirm each active QR code, passenger, and opted-in WhatsApp number before queueing individual messages.
            </p>
          </div>
          <button
            data-dialog-initial-focus
            type="button"
            onClick={onClose}
            disabled={sending}
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
            aria-label="Close QR delivery preview"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="space-y-3">
              <Skeleton className="h-20 rounded-xl" />
              <Skeleton className="h-72 rounded-xl" />
            </div>
          ) : loadError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {loadError.message || "The QR delivery preview could not be loaded."}
            </div>
          ) : preview ? (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <QrDeliverySummary label="Passengers" value={preview.summary.total_passengers} />
                <QrDeliverySummary label="Ready" value={preview.summary.ready} tone="success" />
                <QrDeliverySummary label="Retryable" value={preview.summary.retryable} tone="warning" />
                <QrDeliverySummary label="Already sent" value={preview.summary.already_sent} />
                <QrDeliverySummary label="In progress" value={preview.summary.in_progress} />
                <QrDeliverySummary label="Blocked" value={preview.summary.blocked} tone="danger" />
                {(preview.summary.ambiguous_recipients ?? 0) > 0 && (
                  <QrDeliverySummary
                    label="Shared number"
                    value={preview.summary.ambiguous_recipients ?? 0}
                    tone="danger"
                  />
                )}
              </div>

              {preview.configuration_error && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  {preview.configuration_error}
                </div>
              )}

              {sendFeedback && (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  {sendFeedback} Delivery status refreshes automatically.
                </div>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <label htmlFor="qr-message-content" className="text-sm font-semibold text-slate-900">
                    Editable message
                  </label>
                  <textarea
                    id="qr-message-content"
                    value={messageContent}
                    onChange={(event) => onMessageContentChange(event.target.value)}
                    maxLength={600}
                    rows={6}
                    disabled={sending}
                    className="mt-2 w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100"
                  />
                  <p className="mt-1 text-right text-xs text-slate-400">{messageContent.length}/600</p>
                </div>
                <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
                  <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">
                    {preview.template_name || "qrcode_v1"} preview
                  </div>
                  <div className="mt-3 flex min-h-32 items-center justify-center rounded-lg border border-emerald-100 bg-white p-3">
                    {previewPassenger && qrImages[previewPassenger.passenger_id] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={qrImages[previewPassenger.passenger_id]}
                        alt={`${previewPassenger.passenger_name} QR preview`}
                        className="h-28 w-28"
                      />
                    ) : (
                      <div className="text-center text-xs font-medium text-slate-500">
                        Individual passenger QR image
                      </div>
                    )}
                  </div>
                  <p className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-800 [overflow-wrap:anywhere]">{sampleMessage}</p>
                  <p className="mt-2 text-xs text-slate-500">Each passenger receives only the active QR shown in their row.</p>
                </div>
              </div>

              <div className="overflow-hidden rounded-xl border border-slate-200">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[900px] text-left text-sm">
                    <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-4 py-3">Send</th>
                        <th className="px-4 py-3">Passenger</th>
                        <th className="px-4 py-3">QR code</th>
                        <th className="px-4 py-3">WhatsApp recipient</th>
                        <th className="px-4 py-3">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {preview.recipients.map((row) => (
                        <tr key={row.passenger_id} className={row.eligible ? "bg-white" : "bg-slate-50/60"}>
                          <td className="px-4 py-3">
                            <input
                              type="checkbox"
                              checked={Boolean(row.qr_token_id && selectedQrTokenSet.has(row.qr_token_id))}
                              disabled={!row.eligible || !row.qr_token_id || sending}
                              onChange={() => row.qr_token_id && onToggleQr(row.qr_token_id)}
                              aria-label={`Send QR to ${row.passenger_name}`}
                              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-semibold text-slate-900">{row.passenger_name}</div>
                            <div className="mt-1 text-xs text-slate-500">{row.passport_number || "No passport number"}</div>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              {qrImages[row.passenger_id] ? (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img
                                  src={qrImages[row.passenger_id]}
                                  alt=""
                                  className="h-12 w-12 rounded border border-slate-200 bg-white p-1"
                                />
                              ) : (
                                <QrCode className="h-10 w-10 text-slate-300" aria-hidden="true" />
                              )}
                              <div>
                                <div className="font-medium text-slate-800">
                                  {row.qr_token_version ? `Version ${row.qr_token_version}` : "Not generated"}
                                </div>
                                <div className="mt-1 text-xs text-slate-500">{formatQrStatus(row.qr_status)}</div>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-medium text-slate-800">{row.phone_number || "Not matched"}</div>
                            <div className="mt-1 text-xs text-slate-500">{row.broadcast_name || "No linked broadcast match"}</div>
                          </td>
                          <td className="px-4 py-3">
                            <QrDeliveryPreviewStatus status={row.delivery_status} />
                            <div className="mt-1 max-w-xs text-xs text-slate-500">{row.reason}</div>
                            {row.error_message && row.delivery_status === "retryable" && (
                              <div className="mt-1 max-w-md text-xs font-medium text-red-700">
                                {row.error_message}
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <div className="border-t border-slate-200 px-6 py-4">
          {(sendError || loadError) && (
            <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {(sendError || loadError)?.message}
            </div>
          )}
          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-slate-500">
              Successful and uncertain deliveries are excluded automatically to prevent duplicates.
            </p>
            <div className="flex justify-end gap-3">
              <Button type="button" variant="secondary" onClick={onClose} disabled={sending}>Cancel</Button>
              <Button
                type="button"
                onClick={onSend}
                isLoading={sending}
                disabled={
                  !preview?.can_send ||
                  selectedQrTokenIds.length === 0 ||
                  loading ||
                  !messageContentValid
                }
              >
                <Send className="h-4 w-4" />
                Send individually to {selectedQrTokenIds.length}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
