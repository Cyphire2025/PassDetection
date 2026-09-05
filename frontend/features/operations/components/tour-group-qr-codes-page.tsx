"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, Ban, CheckCircle2, Clock3, Power, Printer, QrCode, RefreshCw, Search, Send, ShieldCheck, UsersRound, X } from "lucide-react";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils/cn";
import {
  WhatsAppActivityInline,
  useWhatsAppActivityTracker,
} from "@/features/whatsapp/components/whatsapp-activity-tracker";
import {
  useGroupQrCodes,
  usePassengerQrLifecycle,
  useQrDeliveryPreview,
  useSendQrBroadcast,
} from "../hooks/use-operations";
import type { GroupPassengerQrCode, QrDeliveryPreview } from "../api/operations.api";
import {
  createQrImageGenerator,
  planQrImageGeneration,
  type CachedQrImage,
} from "../services/qr-image-generation";
import {
  OperationsEmptyState,
  OperationsErrorNotice,
  OperationsPageHeader,
  OperationsSummaryItem,
  OperationsSummaryStrip,
} from "./operations-workspace-ui";

type QrImageMap = Record<string, string>;
type QrStatusFilter = "all" | "active" | "not_generated" | "attention";
const INITIAL_QR_CARD_LIMIT = 48;

export function TourGroupQrCodesPage({ groupId }: { groupId: string }) {
  const { registerActivity } = useWhatsAppActivityTracker();
  const { data, isLoading, error } = useGroupQrCodes(groupId);
  const qrLifecycle = usePassengerQrLifecycle(groupId);
  const [qrImages, setQrImages] = useState<QrImageMap>({});
  const [generatedPayloads, setGeneratedPayloads] = useState<Record<string, string>>({});
  const [pendingPassengerId, setPendingPassengerId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSendPreviewOpen, setIsSendPreviewOpen] = useState(false);
  const [selectedQrTokenIds, setSelectedQrTokenIds] = useState<string[] | null>(null);
  const [messageContent, setMessageContent] = useState<string | null>(null);
  const [deliveryFeedback, setDeliveryFeedback] = useState<string | null>(null);
  const [qrGenerationFailureCount, setQrGenerationFailureCount] = useState(0);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<QrStatusFilter>("all");
  const [renderLimit, setRenderLimit] = useState(INITIAL_QR_CARD_LIMIT);
  const [printRequested, setPrintRequested] = useState(false);
  const [qrImageCache] = useState(
    () => new Map<string, CachedQrImage>(),
  );
  const [qrImageGenerator] = useState(() => createQrImageGenerator());
  const deliveryPreview = useQrDeliveryPreview(groupId, isSendPreviewOpen);
  const sendQrBroadcast = useSendQrBroadcast(groupId);
  const deferredQuery = useDeferredValue(query);
  const filteredPassengers = useMemo(() => {
    const normalized = deferredQuery.trim().toLocaleLowerCase();
    return (data?.passengers ?? []).filter((passenger) => {
      if (statusFilter === "active" && passenger.qr_status !== "active") return false;
      if (statusFilter === "not_generated" && passenger.qr_status !== "not_generated") return false;
      if (statusFilter === "attention" && ["active", "not_generated"].includes(passenger.qr_status)) return false;
      if (!normalized) return true;
      return [passenger.client_name, passenger.client_email, passenger.client_phone, passenger.departure_city, passenger.coordinator_name, passenger.qr_status]
        .some((value) => value?.toLocaleLowerCase().includes(normalized));
    });
  }, [data?.passengers, deferredQuery, statusFilter]);
  const displayedPassengers = useMemo(
    () => printRequested
      ? (data?.passengers ?? [])
      : filteredPassengers.slice(0, renderLimit),
    [data?.passengers, filteredPassengers, printRequested, renderLimit],
  );
  const payloadScopeIds = useMemo(
    () => new Set(
      (printRequested || isSendPreviewOpen ? (data?.passengers ?? []) : displayedPassengers)
        .map((passenger) => passenger.passenger_id),
    ),
    [data?.passengers, displayedPassengers, isSendPreviewOpen, printRequested],
  );

  const visiblePayloads = useMemo(
    () => ({
      ...Object.fromEntries(
        (data?.passengers ?? [])
          .filter((passenger) => payloadScopeIds.has(passenger.passenger_id) && passenger.qr_payload)
          .map((passenger) => [passenger.passenger_id, passenger.qr_payload as string]),
      ),
      ...Object.fromEntries(
        Object.entries(generatedPayloads).filter(([passengerId]) => payloadScopeIds.has(passengerId)),
      ),
    }),
    [data?.passengers, generatedPayloads, payloadScopeIds],
  );

  useEffect(() => {
    const controller = new AbortController();
    let animationFrameId: number | null = null;
    let pendingImages: QrImageMap = {};

    const flushPendingImages = () => {
      animationFrameId = null;
      if (controller.signal.aborted || Object.keys(pendingImages).length === 0) {
        pendingImages = {};
        return;
      }
      const nextImages = pendingImages;
      pendingImages = {};
      setQrImages((current) => ({ ...current, ...nextImages }));
    };

    async function generateQrImages() {
      const revealed = Object.entries(visiblePayloads);
      const visiblePassengerIds = new Set(revealed.map(([passengerId]) => passengerId));
      for (const [passengerId, cached] of qrImageCache) {
        if (
          !visiblePassengerIds.has(passengerId)
          || visiblePayloads[passengerId] !== cached.payload
        ) {
          qrImageCache.delete(passengerId);
        }
      }

      if (revealed.length === 0) {
        setQrImages({});
        setQrGenerationFailureCount(0);
        return;
      }

      const { cachedEntries, pendingEntries } = planQrImageGeneration(
        revealed,
        qrImageCache,
      );
      setQrImages(Object.fromEntries(cachedEntries));
      setQrGenerationFailureCount(0);
      if (pendingEntries.length === 0) return;

      const result = await qrImageGenerator.generate(pendingEntries, {
        signal: controller.signal,
        onEntry: ([passengerId, imageUrl]) => {
          const payload = visiblePayloads[passengerId];
          if (!payload || controller.signal.aborted) return;
          qrImageCache.set(passengerId, { payload, imageUrl });
          pendingImages[passengerId] = imageUrl;
          animationFrameId ??= window.requestAnimationFrame(flushPendingImages);
        },
      });

      if (!controller.signal.aborted) {
        if (animationFrameId !== null) {
          window.cancelAnimationFrame(animationFrameId);
          flushPendingImages();
        }
        setQrGenerationFailureCount(result.failedPassengerIds.length);
        if (printRequested && result.failedPassengerIds.length > 0) {
          setPrintRequested(false);
          setActionError("The print sheet could not be prepared because one or more QR images failed to render. Refresh and try again.");
        }
      }
    }

    void generateQrImages().catch(() => {
      if (!controller.signal.aborted) {
        setQrGenerationFailureCount(1);
        if (printRequested) {
          setPrintRequested(false);
          setActionError("The print sheet could not be prepared because QR images failed to render. Refresh and try again.");
        }
      }
    });
    return () => {
      controller.abort();
      if (animationFrameId !== null) {
        window.cancelAnimationFrame(animationFrameId);
      }
    };
  }, [printRequested, qrImageCache, qrImageGenerator, visiblePayloads]);

  useEffect(() => {
    if (!printRequested) return;
    const payloadPassengerIds = Object.keys(visiblePayloads);
    const allImagesReady = payloadPassengerIds.every((passengerId) => Boolean(qrImages[passengerId]));
    if (!allImagesReady || qrGenerationFailureCount > 0) return;
    const frame = window.requestAnimationFrame(() => {
      window.print();
      setPrintRequested(false);
      setRenderLimit(INITIAL_QR_CARD_LIMIT);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [printRequested, qrGenerationFailureCount, qrImages, visiblePayloads]);

  const defaultSelectedQrTokenIds = (deliveryPreview.data?.recipients ?? [])
    .filter((recipient) => recipient.eligible && recipient.qr_token_id)
    .map((recipient) => recipient.qr_token_id as string);
  const effectiveSelectedQrTokenIds =
    selectedQrTokenIds ?? defaultSelectedQrTokenIds;
  const effectiveMessageContent =
    messageContent ?? deliveryPreview.data?.message_content ?? "";

  const revealToken = async (passengerId: string, regenerate: boolean) => {
    if (regenerate && !window.confirm("Regenerate this QR? The previous printed code will stop working immediately.")) return;
    setPendingPassengerId(passengerId);
    setActionError(null);
    try {
      const result = await (regenerate
        ? qrLifecycle.regenerate.mutateAsync(passengerId)
        : qrLifecycle.generate.mutateAsync(passengerId));
      if (result.qr_payload) {
        setGeneratedPayloads((current) => ({ ...current, [passengerId]: result.qr_payload as string }));
      }
    } catch {
      setActionError("The QR action could not be completed. Refresh and try again.");
    } finally {
      setPendingPassengerId(null);
    }
  };

  const updateLifecycle = async (passengerId: string, action: "revoke" | "expire" | "activate" | "deactivate") => {
    const warnings = {
      revoke: "Revoke this QR permanently? The passenger will need a newly generated code.",
      expire: "Expire this QR now? It will stop scanning immediately.",
      activate: "Activate this QR again? Any existing printed copy will become scannable.",
      deactivate: "Deactivate this QR? It can be activated again later.",
    };
    if (!window.confirm(warnings[action])) return;
    setPendingPassengerId(passengerId);
    setActionError(null);
    try {
      if (action === "revoke") await qrLifecycle.revoke.mutateAsync(passengerId);
      if (action === "expire") await qrLifecycle.expire.mutateAsync(passengerId);
      if (action === "activate") await qrLifecycle.setActive.mutateAsync({ passengerId, isActive: true });
      if (action === "deactivate") await qrLifecycle.setActive.mutateAsync({ passengerId, isActive: false });
      if (action === "revoke" || action === "expire") {
        setGeneratedPayloads((current) => {
          const next = { ...current };
          delete next[passengerId];
          return next;
        });
      }
    } catch {
      setActionError("The QR status could not be updated. Refresh and try again.");
    } finally {
      setPendingPassengerId(null);
    }
  };

  const passengerCount = data?.passengers.length ?? 0;
  const activeCount = data?.passengers.filter((passenger) => passenger.qr_status === "active").length ?? 0;
  const notGeneratedCount = data?.passengers.filter((passenger) => passenger.qr_status === "not_generated").length ?? 0;
  const attentionCount = Math.max(0, passengerCount - activeCount - notGeneratedCount);

  return (
    <div className="space-y-5 print:space-y-4">
      <div className="print:hidden">
        <OperationsPageHeader
          title={data?.group_name ? `${data.group_name} QR codes` : "Group QR codes"}
          description="Generate, print, and send passenger QR codes. Review expired or inactive codes."
          icon={QrCode}
          context={<span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-200"><ShieldCheck className="h-3.5 w-3.5 text-sky-300" aria-hidden="true" />{activeCount} active codes</span>}
          actions={
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                leftIcon={<Send className="h-4 w-4" aria-hidden="true" />}
                onClick={() => {
                  setDeliveryFeedback(null);
                  setSelectedQrTokenIds(null);
                  setMessageContent(null);
                  sendQrBroadcast.reset();
                  setIsSendPreviewOpen(true);
                }}
                disabled={!data || data.passengers.length === 0}
              >
                Send WhatsApp Broadcast
              </Button>
              <Button
                type="button"
                className="bg-white text-slate-950 hover:bg-sky-50 active:bg-sky-100"
                leftIcon={<Printer className="h-4 w-4" aria-hidden="true" />}
                onClick={() => {
                  setActionError(null);
                  setPrintRequested(true);
                  setRenderLimit(passengerCount);
                }}
                isLoading={printRequested}
                disabled={!data || passengerCount === 0}
              >
                {printRequested ? "Preparing print" : "Print all"}
              </Button>
              <Link
                href={ROUTES.dashboard.tourOperationsGroupAssignments}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3.5 text-sm font-semibold text-white transition hover:bg-white/15"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Groups
              </Link>
            </div>
          }
        />
      </div>

      <div className="print:hidden">
        <WhatsAppActivityInline />
      </div>

      <div className="print:hidden">
        <OperationsSummaryStrip label="Passenger QR summary">
          {isLoading ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[72px] rounded-none" />) : (
            <>
              <OperationsSummaryItem label="Passengers" value={passengerCount.toLocaleString()} helper="submitted roster" icon={UsersRound} />
              <OperationsSummaryItem label="Active codes" value={activeCount.toLocaleString()} helper="ready to scan" icon={CheckCircle2} tone={activeCount === passengerCount && passengerCount > 0 ? "success" : "default"} />
              <OperationsSummaryItem label="Not generated" value={notGeneratedCount.toLocaleString()} helper="need a code" icon={QrCode} tone={notGeneratedCount > 0 ? "attention" : "success"} />
              <OperationsSummaryItem label="Lifecycle attention" value={attentionCount.toLocaleString()} helper="inactive or expired" icon={AlertTriangle} tone={attentionCount > 0 ? "attention" : "success"} />
            </>
          )}
        </OperationsSummaryStrip>
      </div>

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
                  {data ? `${data.passengers.length} submitted passenger${data.passengers.length === 1 ? "" : "s"}` : "Loading passengers"}
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
                    isPending={pendingPassengerId === passenger.passenger_id}
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

function QrDeliveryPreviewDialog({
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
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const onCloseRef = useRef(onClose);
  const sendingRef = useRef(sending);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
  useEffect(() => { sendingRef.current = sending; }, [sending]);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !sendingRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
      if (controls.length === 0) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, []);

  const sampleMessage = [
    "Dear Delegates",
    "Greetings from Global Connect Travels",
    messageContent,
    "Regards,\nTeam Global Connect Travels",
  ].join("\n\n");
  const previewPassenger = preview?.recipients.find(
    (recipient) =>
      recipient.qr_token_id && selectedQrTokenIds.includes(recipient.qr_token_id),
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
      <div ref={dialogRef} className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
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
            ref={closeButtonRef}
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
                  <p className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-800">{sampleMessage}</p>
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
                              checked={Boolean(row.qr_token_id && selectedQrTokenIds.includes(row.qr_token_id))}
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

function QrDeliverySummary({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  const toneClass = tone === "success"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : tone === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : tone === "danger"
        ? "border-red-200 bg-red-50 text-red-900"
        : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      <div className="text-xs font-medium opacity-70">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function QrDeliveryPreviewStatus({ status }: { status: string }) {
  const variant = status === "ready"
    ? "success"
    : status === "retryable"
      ? "warning"
      : status === "blocked"
        ? "destructive"
        : "secondary";
  return <Badge variant={variant}>{formatQrStatus(status)}</Badge>;
}

function PassengerQrCard({
  passenger,
  imageUrl,
  payload,
  isPending,
  onGenerate,
  onRegenerate,
  onLifecycle,
}: {
  passenger: GroupPassengerQrCode;
  imageUrl?: string;
  payload?: string;
  isPending: boolean;
  onGenerate: () => void;
  onRegenerate: () => void;
  onLifecycle: (action: "revoke" | "expire" | "activate" | "deactivate") => void;
}) {
  const hasToken = passenger.qr_status !== "not_generated";
  return (
    <article className="break-inside-avoid rounded-xl border border-slate-200 bg-white p-4 shadow-sm [contain-intrinsic-size:260px] [content-visibility:auto] print:rounded-none print:border-slate-300 print:shadow-none print:[content-visibility:visible]">
      <div className="flex gap-4">
        <div className="flex h-36 w-36 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white p-2">
          {imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imageUrl} alt={`${passenger.client_name} attendance QR`} className="h-full w-full" />
          ) : (
            <div className="px-2 text-center print:hidden">
              <ShieldCheck className="mx-auto h-9 w-9 text-slate-300" aria-hidden="true" />
              <p className="mt-2 text-[11px] leading-4 text-slate-400">
                {hasToken ? "Regenerate to restore display" : "Generate to reveal"}
              </p>
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <h3 className="break-words text-base font-semibold text-slate-900">{passenger.client_name}</h3>
          <p className="mt-1 break-all text-xs text-slate-500">
            {[passenger.client_email, passenger.client_phone].filter(Boolean).join(" | ") || "No contact"}
          </p>
          <div className="mt-3">
            <Badge variant="secondary">Shared group access</Badge>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant={statusVariant(passenger.qr_status)} dot>{formatQrStatus(passenger.qr_status)}</Badge>
            {passenger.qr_token_version && <Badge variant="outline">v{passenger.qr_token_version}</Badge>}
          </div>
          {passenger.qr_expires_at && (
            <p className="mt-2 text-[11px] text-slate-500">
              Expires {new Date(passenger.qr_expires_at).toLocaleDateString()}
            </p>
          )}
          {payload && (
            <p className="mt-3 break-all font-mono text-[10px] leading-4 text-slate-400 print:text-slate-500">
              {payload}
            </p>
          )}
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 print:hidden">
        {!hasToken ? (
          <Button type="button" className="col-span-2 gap-2" disabled={isPending} onClick={onGenerate}>
            <QrCode className="h-4 w-4" /> {isPending ? "Generating" : "Generate QR Code"}
          </Button>
        ) : (
          <>
            <Button type="button" className="col-span-2 gap-2" disabled={isPending} onClick={onRegenerate}>
              <RefreshCw className="h-4 w-4" /> {isPending ? "Updating" : "Regenerate QR Code"}
            </Button>
            {passenger.qr_status === "active" && (
              <Button type="button" variant="secondary" disabled={isPending} onClick={() => onLifecycle("deactivate")}>
                <Power className="mr-1.5 h-4 w-4" /> Deactivate
              </Button>
            )}
            {passenger.qr_status === "inactive" && (
              <Button type="button" variant="secondary" disabled={isPending} onClick={() => onLifecycle("activate")}>
                <Power className="mr-1.5 h-4 w-4" /> Activate
              </Button>
            )}
            {(passenger.qr_status === "active" || passenger.qr_status === "inactive") && (
              <Button type="button" variant="outline" disabled={isPending} onClick={() => onLifecycle("expire")}>
                <Clock3 className="mr-1.5 h-4 w-4" /> Expire now
              </Button>
            )}
            {passenger.qr_status !== "revoked" && (
              <Button type="button" variant="danger" className="col-span-2" disabled={isPending} onClick={() => onLifecycle("revoke")}>
                <Ban className="mr-1.5 h-4 w-4" /> Revoke permanently
              </Button>
            )}
          </>
        )}
      </div>
    </article>
  );
}

function formatQrStatus(status: string) {
  return status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function statusVariant(status: string): "default" | "success" | "warning" | "destructive" | "outline" {
  if (status === "active") return "success";
  if (status === "inactive" || status === "expired") return "warning";
  if (status === "revoked") return "destructive";
  return "outline";
}
