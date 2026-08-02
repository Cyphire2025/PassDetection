"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Ban, Clock3, Power, Printer, QrCode, RefreshCw, Send, ShieldCheck, X } from "lucide-react";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
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

type QrImageMap = Record<string, string>;

export function TourGroupQrCodesPage({ groupId }: { groupId: string }) {
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
  const [qrImageCache] = useState(
    () => new Map<string, CachedQrImage>(),
  );
  const [qrImageGenerator] = useState(() => createQrImageGenerator());
  const deliveryPreview = useQrDeliveryPreview(groupId, isSendPreviewOpen);
  const sendQrBroadcast = useSendQrBroadcast(groupId);

  const visiblePayloads = useMemo(
    () => ({
      ...Object.fromEntries(
        (data?.passengers ?? [])
          .filter((passenger) => passenger.qr_payload)
          .map((passenger) => [passenger.passenger_id, passenger.qr_payload as string]),
      ),
      ...generatedPayloads,
    }),
    [data?.passengers, generatedPayloads],
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
      }
    }

    void generateQrImages().catch(() => {
      if (!controller.signal.aborted) {
        setQrGenerationFailureCount(1);
      }
    });
    return () => {
      controller.abort();
      if (animationFrameId !== null) {
        window.cancelAnimationFrame(animationFrameId);
      }
    };
  }, [qrImageCache, qrImageGenerator, visiblePayloads]);

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

  return (
    <div className="space-y-6 print:space-y-4">
      <div className="print:hidden">
        <PageHeader
          title={data?.group_name ? `${data.group_name} QR Codes` : "Group QR Codes"}
          description="Print or share these passenger QR cards for coordinator attendance scanning."
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
                variant="secondary"
                leftIcon={<Printer className="h-4 w-4" aria-hidden="true" />}
                onClick={() => window.print()}
                disabled={Object.keys(qrImages).length === 0}
              >
                Print
              </Button>
              <Link
                href={ROUTES.dashboard.tourOperationsGroupAssignments}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Groups
              </Link>
            </div>
          }
        />
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 print:hidden">
          QR codes could not be loaded.
        </div>
      )}

      {actionError && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 print:hidden">
          {actionError}
        </div>
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

      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800 print:hidden">
        Generated QR cards stay visible here for office users. Use Regenerate only when the printed code must be replaced.
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

          {isLoading ? (
            <div className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-64 rounded-xl" />
              ))}
            </div>
          ) : !data || data.passengers.length === 0 ? (
            <div className="p-5">
              <p className="rounded-lg border border-dashed border-slate-300 px-3 py-8 text-center text-sm text-slate-500">
                No submitted passengers found for this group.
              </p>
            </div>
          ) : (
            <div className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-3 print:grid-cols-2 print:p-0">
              {data.passengers.map((passenger) => (
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
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
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
    <article className="break-inside-avoid rounded-xl border border-slate-200 bg-white p-4 shadow-sm print:rounded-none print:border-slate-300 print:shadow-none">
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
