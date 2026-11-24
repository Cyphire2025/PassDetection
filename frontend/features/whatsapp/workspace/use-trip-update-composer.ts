"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ROUTES } from "@/constants/routes";
import { groupUpdatesApi, type GroupUpdateAudience } from "../api/group-updates.api";
import { useGroupUpdateSend } from "../hooks/use-group-update-send";
import { useWhatsAppActivityTracker } from "../components/whatsapp-activity-tracker";
import { useBroadcast } from "./broadcast-workspace-shell";

export function useTripUpdateComposer(groupId: string) {
  const broadcast = useBroadcast();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { registerActivity } = useWhatsAppActivityTracker();
  const [audience, setAudience] = useState<GroupUpdateAudience>({
    submission_status: "all",
    document_status: "all",
    document_type: "visa",
  });
  const [content, setContent] = useState("");
  const [selected, setSelected] = useState<string[] | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const preview = useQuery({
    queryKey: ["group-update-preview", groupId, audience],
    queryFn: ({ signal }) => groupUpdatesApi.preview(groupId, audience, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchInterval: (query) =>
      query.state.status === "success" && query.state.data?.recipients.some((row) =>
        ["queued", "processing"].includes(row.latest_update_status ?? ""),
      )
        ? 5000
        : false,
  });
  const rows = (preview.data?.recipients ?? []).filter(
    (row) => row.broadcast_group_id === broadcast.id,
  );
  const selectedSet = selected === null ? null : new Set(selected);
  const chosen = rows.filter(
    (row) =>
      row.eligible &&
      (selectedSet === null
        ? row.latest_update_status === null
        : selectedSet.has(row.audience_key)),
  );
  const chosenKeys = new Set(chosen.map((row) => row.audience_key));
  const numbers = new Set(chosen.map((row) => row.phone_number)).size;
  const person =
    rows.find((row) => row.audience_key === previewKey) ?? chosen[0] ?? rows[0];
  const normalized = content.replace(/\s+/gu, " ").trim();
  const message = `Dear Delegates\n\nGreetings from Global Connect Travels.\n\n${normalized || "[Your update message]"}\n\nRegards,\nTeam Global Connect Travels`;
  const { send, submittedRequest, submit: submitRequest } = useGroupUpdateSend(groupId, (result) => {
    for (const batch of result.batches ?? [])
      registerActivity({
        id: batch.batch_id,
        kind: "broadcast",
        messageType: "document_update",
        startedAt: Date.now(),
        title: "Trip update",
        contextLabel: broadcast.name,
        sourceGroupId: batch.broadcast_group_id,
        documentType: null,
        total: batch.queued_count,
        queued: batch.queued_count,
        sent: 0,
        failed: 0,
        deliveryUnknown: 0,
      });
    void queryClient.invalidateQueries({
      queryKey: ["whatsapp", "history", broadcast.id],
    });
    const batch = result.batches?.find(
      (item) => item.broadcast_group_id === broadcast.id,
    );
    if (batch)
      router.push(
        `${ROUTES.dashboard.whatsappBroadcastHistory(broadcast.id)}?message=${encodeURIComponent(batch.batch_id)}`,
      );
  });
  const locked = send.isPending || send.isSuccess || submittedRequest !== null;
  const ready = Boolean(
    preview.data?.can_send &&
    !preview.isFetching &&
    !preview.isError &&
    normalized &&
    numbers &&
    !broadcast.is_archived,
  );
  function submit() {
    submitRequest(() => {
      if (!ready || !preview.data) return null;
      return {
        request_id: crypto.randomUUID(),
        preview_token: preview.data.preview_token,
        audience,
        audience_keys: chosen.map((row) => row.audience_key),
        message_content: normalized,
      };
    });
  }
  return {
    broadcast, audience, setAudience, content, setContent,
    setSelected, setPreviewKey, reviewing, setReviewing,
    preview, rows, chosen, chosenKeys, numbers, person, message,
    send, submittedRequest, locked, ready, submit,
  };
}
