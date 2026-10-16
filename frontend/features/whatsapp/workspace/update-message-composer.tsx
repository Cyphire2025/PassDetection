"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { RefreshCw, Send } from "lucide-react";
import { Button } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { distributionDocumentLabel } from "@/features/documents/config/document-distribution-lanes";
import { DOCUMENT_DISTRIBUTION_LANES } from "@/features/documents/config/document-distribution-lanes";
import type { ApiError } from "@/lib/api/client";
import {
  groupUpdatesApi,
  type GroupUpdateAudience,
  type GroupUpdateRequest,
} from "../api/group-updates.api";
import { GroupUpdateRecipientPicker } from "../components/group-update-recipient-picker";
import { DialogFrame, ErrorBanner } from "../components/whatsapp-dialog-ui";
import { useWhatsAppActivityTracker } from "../components/whatsapp-activity-tracker";
import { useBroadcast } from "./broadcast-workspace-shell";
import { ComposerPreview, ComposerTextField } from "./composer-primitives";
import { fieldClass } from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function UpdateMessageComposer() {
  const broadcast = useBroadcast();
  const groups = (broadcast.linked_client_groups ?? []).filter(
    (group) => !["archived", "deleted"].includes(group.status),
  );
  const [groupId, setGroupId] = useState(
    groups.length === 1 ? groups[0].id : "",
  );
  if (!groupId)
    return (
      <div className={`${styles.surface} space-y-4 p-6`}>
        <h2 className="text-lg font-semibold">Trip update</h2>
        {groups.length ? (
          <label className="block text-sm font-medium">
            Submission group for audience filters
            <select
              className={`mt-2 ${fieldClass}`}
              value={groupId}
              onChange={(event) => setGroupId(event.target.value)}
            >
              <option value="">Choose the linked group</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="text-sm text-slate-500">
            Link this broadcast to a client group in All Groups to use
            submission and document filters.
          </p>
        )}
      </div>
    );
  return <UpdateComposer key={groupId} groupId={groupId} />;
}

function UpdateComposer({ groupId }: { groupId: string }) {
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
  const [submittedRequest, setSubmittedRequest] =
    useState<GroupUpdateRequest | null>(null);
  const preview = useQuery({
    queryKey: ["group-update-preview", groupId, audience],
    queryFn: ({ signal }) => groupUpdatesApi.preview(groupId, audience, signal),
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.data?.recipients.some((row) =>
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
  const send = useMutation({
    mutationFn: (request: GroupUpdateRequest) =>
      groupUpdatesApi.send(groupId, request),
    retry: false,
    onSuccess: (result) => {
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
    },
    onError: (error: ApiError) => {
      if ([400, 403, 404, 409, 422].includes(error.status ?? 0))
        setSubmittedRequest(null);
    },
  });
  const locked = send.isPending || submittedRequest !== null;
  const ready = Boolean(
    preview.data?.can_send &&
    !preview.isFetching &&
    !preview.isError &&
    normalized &&
    numbers &&
    !broadcast.is_archived,
  );
  function submit() {
    if (submittedRequest) {
      send.mutate(submittedRequest);
      return;
    }
    if (!ready || !preview.data) return;
    const request = {
      request_id: crypto.randomUUID(),
      preview_token: preview.data.preview_token,
      audience,
      audience_keys: chosen.map((row) => row.audience_key),
      message_content: normalized,
    };
    setSubmittedRequest(request);
    send.mutate(request);
  }
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">Trip update</h2>
        <p className="mt-1 text-sm text-slate-500">
          Write your update, choose its audience and review the individual
          message.
        </p>
      </div>
      <section
        aria-label="Message editor and preview"
        className={`${styles.surface} p-5 sm:p-6`}
      >
        <div className="grid items-start gap-7 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          <fieldset
            disabled={locked || Boolean(broadcast.is_archived)}
            className="min-w-0 space-y-5"
          >
            <h3 className="border-b border-slate-100 pb-3 text-sm font-semibold">
              Write your message
            </h3>
            <ComposerTextField
              label="Update message"
              value={content}
              onChange={setContent}
            />
            <p className="text-xs leading-5 text-slate-500">
              The greeting and sign-off use your approved update template. Extra
              spaces and line breaks in this paragraph become single spaces.
            </p>
          </fieldset>
          <aside
            aria-label="Live WhatsApp preview"
            className="min-w-0 lg:sticky lg:top-5"
          >
            <h3 className="mb-3 text-sm font-semibold">WhatsApp preview</h3>
            <ComposerPreview
              message={message}
              recipientName={person?.name}
              current={
                !preview.isFetching && !preview.isError && Boolean(preview.data)
              }
            >
              <label className="block text-xs font-medium text-slate-500">
                Preview recipient
                <select
                  className={`mt-1.5 ${fieldClass}`}
                  value={person?.audience_key ?? ""}
                  onChange={(event) => setPreviewKey(event.target.value)}
                  disabled={!rows.length}
                >
                  {rows.map((row) => (
                    <option key={row.audience_key} value={row.audience_key}>
                      {row.name} · {row.phone_number ?? "Number unavailable"}
                    </option>
                  ))}
                </select>
              </label>
            </ComposerPreview>
          </aside>
        </div>
      </section>
      <section
        aria-label="Message audience"
        className={`${styles.surface} space-y-5 p-5 sm:p-6`}
      >
        <h3 className="text-sm font-semibold">Choose recipients</h3>
        <fieldset disabled={locked} className="grid gap-4 sm:grid-cols-3">
          <label className="text-xs font-medium text-slate-600">
            Document submission
            <select
              className={`mt-2 ${fieldClass}`}
              value={audience.submission_status}
              onChange={(event) => {
                setAudience({
                  ...audience,
                  submission_status: event.target
                    .value as GroupUpdateAudience["submission_status"],
                });
                setSelected(null);
              }}
            >
              <option value="all">Everyone</option>
              <option value="submitted">Submitted</option>
              <option value="not_submitted">Not submitted</option>
            </select>
          </label>
          <label className="text-xs font-medium text-slate-600">
            Document delivery
            <select
              className={`mt-2 ${fieldClass}`}
              value={audience.document_status}
              onChange={(event) => {
                setAudience({
                  ...audience,
                  document_status: event.target
                    .value as GroupUpdateAudience["document_status"],
                });
                setSelected(null);
              }}
            >
              <option value="all">Any status</option>
              <option value="sent">Sent</option>
              <option value="pending">Pending</option>
            </select>
          </label>
          <label className="text-xs font-medium text-slate-600">
            Document type
            <select
              className={`mt-2 ${fieldClass}`}
              value={audience.document_type}
              onChange={(event) => {
                setAudience({
                  ...audience,
                  document_type: event.target
                    .value as GroupUpdateAudience["document_type"],
                });
                setSelected(null);
              }}
            >
              {Object.values(DOCUMENT_DISTRIBUTION_LANES).map((lane) => (
                <option key={lane.documentType} value={lane.documentType}>
                  {lane.workflowLabel}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
        <p className="text-xs text-slate-500">
          Filters apply together. Previous recipients are excluded initially;
          choose them explicitly to send another update.
        </p>
        {preview.error && (
          <ErrorBanner message="Could not load the update audience. Refresh and try again." />
        )}
        {preview.data?.configuration_error && (
          <ErrorBanner message={preview.data.configuration_error} />
        )}
        <GroupUpdateRecipientPicker
          rows={rows}
          selectedKeys={chosenKeys}
          disabled={locked}
          loading={preview.isFetching}
          documentLabel={distributionDocumentLabel(audience.document_type)}
          onChange={setSelected}
        />
      </section>
      {send.error && (
        <ErrorBanner
          message={
            (send.error as unknown as ApiError).message ||
            "The request could not be confirmed. Check the same request before creating another send."
          }
        />
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white py-4">
        <p className="text-xs text-slate-500">
          {numbers} WhatsApp numbers selected · each number receives one message
        </p>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            disabled={locked || preview.isFetching}
            onClick={() => void preview.refetch()}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh preview
          </Button>
          <Button
            disabled={!submittedRequest && !ready}
            onClick={() => setReviewing(true)}
          >
            Review message
          </Button>
        </div>
      </div>
      {reviewing && (
        <DialogFrame
          title="Review trip update"
          description={broadcast.name}
          isBusy={send.isPending}
          onClose={() => setReviewing(false)}
        >
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              {numbers} individual WhatsApp messages · {chosen.length} people
            </p>
            <div className="whitespace-pre-wrap rounded-xl bg-emerald-50 p-5 text-sm leading-6">
              {message}
            </div>
            {send.error && (
              <ErrorBanner
                message={
                  (send.error as unknown as ApiError).message ||
                  "Could not confirm the request. Retry the same request."
                }
              />
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                disabled={send.isPending}
                onClick={() => setReviewing(false)}
              >
                Back to editor
              </Button>
              <Button
                isLoading={send.isPending}
                disabled={!submittedRequest && !ready}
                onClick={submit}
              >
                <Send className="h-4 w-4" />
                {submittedRequest && send.isError
                  ? "Check same send request"
                  : `Send ${numbers} messages`}
              </Button>
            </div>
          </div>
        </DialogFrame>
      )}
    </div>
  );
}
