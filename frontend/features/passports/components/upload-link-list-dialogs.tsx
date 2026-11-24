import dynamic from "next/dynamic";
import { ConfirmDialog } from "@/components/ui";
import { EditGroupDialog } from "./edit-group-dialog";
import { GroupDeleteRetentionDialog } from "./group-delete-retention-dialog";
import type { UploadLinkListState } from "./use-upload-link-list";
const CreateUploadLinkModal = dynamic(
  () => import("./create-upload-link-modal").then((module) => module.CreateUploadLinkModal),
  { loading: () => null },
);

export function UploadLinkListCreateDialog({ state }: { state: UploadLinkListState }) {
  const { isModalOpen, setIsModalOpen } = state;
  return <>{isModalOpen && (
    <CreateUploadLinkModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} />
  )}</>;
}

export function UploadLinkListActionDialogs({ state }: { state: UploadLinkListState }) {
  const {
    confirmAction,
    isClosing,
    isArchiving,
    isRestoring,
    isPermanentlyDeleting,
    setConfirmAction,
    renameTarget,
    setRenameTarget,
    deleteTarget,
    isPermanentDeleteError,
    permanentDeleteError,
    setDeleteTarget,
    permanentlyDeleteLink
  } = state;
  return (
    <>
      <ConfirmDialog
        isOpen={Boolean(confirmAction)}
        title={confirmAction?.title ?? ""}
        description={confirmAction?.description ?? ""}
        confirmLabel={confirmAction?.confirmLabel ?? "Confirm"}
        variant={confirmAction?.variant}
        isLoading={isClosing || isArchiving || isRestoring || isPermanentlyDeleting}
        onClose={() => setConfirmAction(null)}
        onConfirm={() => confirmAction?.onConfirm()}

      />
      {renameTarget && <EditGroupDialog key={renameTarget.id} group={renameTarget} onClose={() => setRenameTarget(null)} />}
      <GroupDeleteRetentionDialog
        group={deleteTarget}
        isLoading={isPermanentlyDeleting}
        error={isPermanentDeleteError
          ? permanentDeleteError?.message || "The group could not be deleted. Please try again."
          : null}
        onClose={() => setDeleteTarget(null)}
        onKeepData={() => {
          if (!deleteTarget) return;
          permanentlyDeleteLink(
            { id: deleteTarget.id, retainRecords: true },
            { onSuccess: () => setDeleteTarget(null) },
          );
        }}
        onDeleteData={() => {
          if (!deleteTarget) return;
          permanentlyDeleteLink(
            { id: deleteTarget.id, retainRecords: false },
            { onSuccess: () => setDeleteTarget(null) },
          );
        }}

      />
    </>
  );
}
