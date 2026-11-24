import { ConfirmDialog } from "@/components/ui";
import { rowPrimaryName, createRosterRequestId } from "./group-whatsapp-tracking-model";
import { ReplacementDialog, ManageBroadcastsDialog } from "./group-whatsapp-dialogs";
import type { GroupWhatsAppTrackingModel } from "./use-group-whatsapp-tracking";

type Props = Pick<
  GroupWhatsAppTrackingModel,
  | "groupId"
  | "setMatchFilter"
  | "setMatchPage"
  | "isManaging"
  | "setIsManaging"
  | "replacementRow"
  | "setReplacementRow"
  | "rejectRow"
  | "setRejectRow"
  | "rejectRequestId"
  | "setRejectRequestId"
  | "restoreRow"
  | "setRestoreRow"
  | "setResolutionError"
  | "links"
  | "rejectUpload"
  | "restoreResolution"
>;

export function GroupWhatsAppResolutionDialogs({
  groupId,
  setMatchFilter,
  setMatchPage,
  isManaging,
  setIsManaging,
  replacementRow,
  setReplacementRow,
  rejectRow,
  setRejectRow,
  rejectRequestId,
  setRejectRequestId,
  restoreRow,
  setRestoreRow,
  setResolutionError,
  links,
  rejectUpload,
  restoreResolution,
}: Props) {
  return (
    <>
      {isManaging && (
        <ManageBroadcastsDialog
          groupId={groupId}
          initialBroadcasts={links?.broadcasts ?? []}
          onClose={() => setIsManaging(false)}
        />
      )}
      {replacementRow && (
        <ReplacementDialog
          groupId={groupId}
          row={replacementRow}
          onClose={() => setReplacementRow(null)}
          onResolved={() => {
            setReplacementRow(null);
            setMatchFilter("replacement");
            setMatchPage(1);
          }}
        />
      )}
      <ConfirmDialog
        isOpen={Boolean(rejectRow)}
        title="Reject and remove this unidentified upload?"
        description={`${
          rejectRow ? rowPrimaryName(rejectRow) : "This upload"
        } will move to Removed uploads. Nothing is deleted, and you can add the upload back later.`}
        confirmLabel="Reject/remove upload"
        variant="danger"
        isLoading={rejectUpload.isPending}
        onClose={() => {
          setRejectRow(null);
          setRejectRequestId(null);
        }}
        onConfirm={() => {
          const submissionId = rejectRow?.submission_ids[0];
          if (!submissionId) {
            setRejectRow(null);
            setRejectRequestId(null);
            setResolutionError("This upload could not be selected. Refresh and try again.");
            return;
          }
          setResolutionError(null);
          rejectUpload.mutate(
            {
              submissionId,
              requestId: rejectRequestId ?? createRosterRequestId(),
            },
            {
              onSuccess: () => {
                setRejectRow(null);
                setRejectRequestId(null);
                setMatchFilter("rejected_upload");
                setMatchPage(1);
              },
              onError: () => {
                setRejectRow(null);
                setRejectRequestId(null);
                setResolutionError(
                  "The unidentified upload could not be removed. Refresh and try again.",
                );
              },
            },
          );
        }}
      />
      <ConfirmDialog
        isOpen={Boolean(restoreRow)}
        title={
          restoreRow?.status === "replacement"
            ? "Restore the original recipient?"
            : "Add this upload back?"
        }
        description={
          restoreRow?.status === "replacement"
            ? "The original WhatsApp recipient will become active for future messages again, and this replacement upload will return to Unidentified uploads."
            : "This upload will return to Unidentified uploads so you can review or assign it again."
        }
        confirmLabel={
          restoreRow?.status === "replacement"
            ? "Restore original recipient"
            : "Add upload back"
        }
        isLoading={restoreResolution.isPending}
        onClose={() => setRestoreRow(null)}
        onConfirm={() => {
          const resolutionId = restoreRow?.resolution_id;
          if (!resolutionId) {
            setRestoreRow(null);
            setResolutionError("This record could not be restored. Refresh and try again.");
            return;
          }
          setResolutionError(null);
          restoreResolution.mutate(resolutionId, {
            onSuccess: () => {
              setRestoreRow(null);
              setMatchFilter("unmatched_submission");
              setMatchPage(1);
            },
            onError: () => {
              setRestoreRow(null);
              setResolutionError(
                "This record could not be restored. Refresh and try again.",
              );
            },
          });
        }}
      />
    </>
  );
}
