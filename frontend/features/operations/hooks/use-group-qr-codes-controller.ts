import { useDeferredValue, useMemo, useState } from "react";
import { useWhatsAppActivityTracker } from "@/features/whatsapp/components/whatsapp-activity-tracker";
import { useGroupQrCodes, useQrDeliveryPreview, useSendQrBroadcast } from "./use-operations";
import type { QrStatusFilter } from "../components/group-qr-model";
import { INITIAL_QR_CARD_LIMIT } from "../components/group-qr-model";
import { usePassengerQrActions } from "./use-passenger-qr-actions";
import { useGroupQrImages } from "./use-group-qr-images";

export function useGroupQrCodesController(groupId: string) {
  const { registerActivity } = useWhatsAppActivityTracker();
  const { data, isLoading, error, refetch } = useGroupQrCodes(groupId);
  const { generatedPayloads, pendingPassengerIds, actionError, setActionError, revealToken, updateLifecycle } = usePassengerQrActions(groupId);

  const [isSendPreviewOpen, setIsSendPreviewOpen] = useState(false);
  const [selectedQrTokenIds, setSelectedQrTokenIds] = useState<string[] | null>(null);
  const [messageContent, setMessageContent] = useState<string | null>(null);
  const [deliveryFeedback, setDeliveryFeedback] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<QrStatusFilter>("all");
  const [renderLimit, setRenderLimit] = useState(INITIAL_QR_CARD_LIMIT);
  const [printRequested, setPrintRequested] = useState(false);
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
  const { qrImages, qrGenerationFailureCount } = useGroupQrImages({
    visiblePayloads, printRequested, setPrintRequested, setRenderLimit, setActionError,
  });
  const defaultSelectedQrTokenIds = (deliveryPreview.data?.recipients ?? [])
    .filter((recipient) => recipient.eligible && recipient.qr_token_id)
    .map((recipient) => recipient.qr_token_id as string);
  const effectiveSelectedQrTokenIds =
    selectedQrTokenIds ?? defaultSelectedQrTokenIds;
  const effectiveMessageContent =
    messageContent ?? deliveryPreview.data?.message_content ?? "";

  const passengerCount = data?.passengers.length ?? 0;
  const activeCount = data?.passengers.filter((passenger) => passenger.qr_status === "active").length ?? 0;
  const notGeneratedCount = data?.passengers.filter((passenger) => passenger.qr_status === "not_generated").length ?? 0;
  const attentionCount = Math.max(0, passengerCount - activeCount - notGeneratedCount);
  const summaryUnavailable = Boolean(error && !data);
  return {
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
    setActionError,
    setPrintRequested,
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
  };
}
