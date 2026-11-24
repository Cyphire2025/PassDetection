"use client";

import { QrCode, Search, ShieldCheck, X } from "lucide-react";
import { Button, Card, CardContent, Skeleton } from "@/components/ui";
import { cn } from "@/lib/utils/cn";
import { OperationsEmptyState, OperationsErrorNotice } from "./operations-workspace-ui";
import type { useGroupQrCodesController } from "../hooks/use-group-qr-codes-controller";
import { INITIAL_QR_CARD_LIMIT } from "./group-qr-model";
import { PassengerQrCard } from "./passenger-qr-card";
import { QrDeliveryPreviewDialog } from "./qr-delivery-preview-dialog";
import { GroupQrPageHeader } from "./group-qr-page-header";

export function GroupQrCodesView({ model }: { model: ReturnType<typeof useGroupQrCodesController> }) {
  const {
    data,
    isLoading,
    error,
    refetch,
    activeCount,
    summaryUnavailable,
    passengerCount,
    notGeneratedCount,
    attentionCount,
    setDeliveryFeedback,
    setSelectedQrTokenIds,
    setMessageContent,
    sendQrBroadcast,
    setIsSendPreviewOpen,
    setRenderLimit,
    printRequested,
    actionError,
    qrGenerationFailureCount,
    deliveryFeedback,
    query,
    setQuery,
    statusFilter,
    setStatusFilter,
    displayedPassengers,
    filteredPassengers,
    qrImages,
    visiblePayloads,
    pendingPassengerIds,
    revealToken,
    updateLifecycle,
    isSendPreviewOpen,
    deliveryPreview,
    effectiveSelectedQrTokenIds,
    effectiveMessageContent,
    defaultSelectedQrTokenIds,
    registerActivity,
    groupId,
  } = model;
  return (
    <div className="space-y-5 print:space-y-4">
      <GroupQrPageHeader model={model} />

      {error && (
        <div className="print:hidden"><OperationsErrorNotice>QR codes could not be refreshed. Previously loaded card status remains visible where available.</OperationsErrorNotice></div>
      )}

      {actionError && (
        <div className="print:hidden"><OperationsErrorNotice>{actionError}</OperationsErrorNotice></div>
      )}

      {qrGenerationFailureCount > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 print:hidden">
          {qrGenerationFailureCount} QR image
          {qrGenerationFailureCount === 1 ? "" : "s"} could not be rendered.
          Refresh to retry; other QR cards remain available.
        </div>
      )}

      {deliveryFeedback && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 print:hidden">
          {deliveryFeedback}
        </div>
      )}

      <div className="flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900 print:hidden">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-blue-700" aria-hidden="true" />
        <span>Generated QR cards remain visible to authorized office users. Regenerate only when an existing printed code must stop working.</span>
      </div>

      <Card className="print:border-0 print:shadow-none">
        <CardContent className="p-0 print:p-0">
          <div className="flex items-center justify-between gap-3 border-b border-slate-200 p-5 print:p-0 print:pb-4">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600 print:hidden">
                <QrCode className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900 print:text-xl">
                  {data?.group_name ?? "Passenger QR Sheet"}
                </h2>
                <p className="text-sm text-slate-500 print:text-xs">
                  {data ? `${data.passengers.length} submitted passenger${data.passengers.length === 1 ? "" : "s"}` : summaryUnavailable ? "Passenger status unavailable" : "Loading passengers"}
                </p>
              </div>
            </div>
            {data?.generated_at && (
              <p className="hidden text-xs text-slate-500 print:block">
                Generated {new Date(data.generated_at).toLocaleString()}
              </p>
            )}
          </div>

          <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 print:hidden sm:px-5">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="relative min-w-0 flex-1 xl:max-w-lg">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
                <input
                  type="search"
                  value={query}
                  onChange={(event) => { setQuery(event.target.value); setRenderLimit(INITIAL_QR_CARD_LIMIT); }}
                  placeholder="Search passenger, phone, city, coordinator, or QR status"
                  aria-label="Search passenger QR cards"
                  className="h-10 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-9 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
                {query && <button type="button" onClick={() => { setQuery(""); setRenderLimit(INITIAL_QR_CARD_LIMIT); }} aria-label="Clear QR search" className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="h-4 w-4" aria-hidden="true" /></button>}
              </div>
              <div className="flex gap-2 overflow-x-auto" aria-label="Filter passenger QR status">
                {([
                  ["all", "All", passengerCount],
                  ["active", "Active", activeCount],
                  ["not_generated", "Not generated", notGeneratedCount],
                  ["attention", "Attention", attentionCount],
                ] as const).map(([value, label, count]) => (
                  <button key={value} type="button" onClick={() => { setStatusFilter(value); setRenderLimit(INITIAL_QR_CARD_LIMIT); }} aria-pressed={statusFilter === value} className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors", statusFilter === value ? "border-blue-700 bg-blue-700 text-white" : "border-slate-200 bg-white text-slate-600 hover:bg-blue-50")}>
                    {label}<span className={statusFilter === value ? "text-blue-100" : "text-slate-400"}>{count}</span>
                  </button>
                ))}
              </div>
            </div>
            <p className="mt-2 text-xs text-slate-500" aria-live="polite">Showing {Math.min(displayedPassengers.length, filteredPassengers.length)} of {filteredPassengers.length} matching passengers</p>
          </div>

          {isLoading ? (
            <div className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-64 rounded-xl" />
              ))}
            </div>
          ) : summaryUnavailable ? (
            <OperationsEmptyState title="QR cards could not be loaded" description="Retry to load the current passenger roster and QR status." action={<Button type="button" variant="secondary" onClick={() => void refetch()}>Retry QR cards</Button>} />
          ) : !data || data.passengers.length === 0 ? (
            <OperationsEmptyState title="No submitted passengers are available" description="QR cards appear after passengers have submitted their details for this group." />
          ) : filteredPassengers.length === 0 ? (
            <OperationsEmptyState filtered title="No QR cards match this view" description="Clear the search or switch the lifecycle filter to restore passenger cards." action={<button type="button" onClick={() => { setQuery(""); setStatusFilter("all"); }} className="text-sm font-semibold text-blue-700 hover:text-blue-900">Reset QR view</button>} />
          ) : (
            <>
              <div className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-3 print:grid-cols-2 print:p-0">
                {displayedPassengers.map((passenger) => (
                  <PassengerQrCard
                    key={passenger.passenger_id}
                    passenger={passenger}
                    imageUrl={qrImages[passenger.passenger_id]}
                    payload={visiblePayloads[passenger.passenger_id]}
                    isPending={pendingPassengerIds.has(passenger.passenger_id)}
                    onGenerate={() => void revealToken(passenger.passenger_id, false)}
                    onRegenerate={() => void revealToken(passenger.passenger_id, true)}
                    onLifecycle={(action) => void updateLifecycle(passenger.passenger_id, action)}
                  />
                ))}
              </div>
              {!printRequested && displayedPassengers.length < filteredPassengers.length && (
                <div className="flex justify-center border-t border-slate-200 bg-slate-50/70 px-5 py-4 print:hidden">
                  <Button type="button" variant="secondary" onClick={() => setRenderLimit((current) => current + INITIAL_QR_CARD_LIMIT)}>
                    Show next {Math.min(INITIAL_QR_CARD_LIMIT, filteredPassengers.length - displayedPassengers.length)} passengers
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {isSendPreviewOpen && (
        <QrDeliveryPreviewDialog
          preview={deliveryPreview.data}
          loading={deliveryPreview.isLoading}
          loadError={deliveryPreview.error}
          qrImages={qrImages}
          selectedQrTokenIds={effectiveSelectedQrTokenIds}
          messageContent={effectiveMessageContent}
          sending={sendQrBroadcast.isPending}
          sendError={sendQrBroadcast.error}
          sendFeedback={deliveryFeedback}
          onMessageContentChange={setMessageContent}
          onToggleQr={(qrTokenId) => {
            setSelectedQrTokenIds((current) =>
              (current ?? defaultSelectedQrTokenIds).includes(qrTokenId)
                ? (current ?? defaultSelectedQrTokenIds).filter((id) => id !== qrTokenId)
                : [...(current ?? defaultSelectedQrTokenIds), qrTokenId],
            );
          }}
          onClose={() => {
            if (!sendQrBroadcast.isPending) setIsSendPreviewOpen(false);
          }}
          onSend={() => {
            setDeliveryFeedback(null);
            sendQrBroadcast.mutate(
              {
                qr_token_ids: effectiveSelectedQrTokenIds,
                message_content: effectiveMessageContent.trim(),
              },
              {
                onSuccess: (result) => {
                  if (result.send_batch_id) {
                    registerActivity({
                      id: result.send_batch_id,
                      kind: "qr",
                      startedAt: Date.now(),
                      title: "QR code broadcast",
                      contextLabel: data?.group_name ?? "Passenger QR codes",
                      sourceGroupId: groupId,
                      documentType: null,
                      total: result.queued_count,
                      queued: result.queued_count,
                      sent: 0,
                      failed: 0,
                      deliveryUnknown: 0,
                    });
                  }
                  setDeliveryFeedback(result.message);
                },
              },
            );
          }}
        />
      )}
    </div>
  );
}
