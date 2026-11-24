import { Archive, Link2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WorkspaceHeaderContext, WorkspacePageHeader } from "@/components/shared/workspace-ui";
import type { UploadLinkListState } from "./use-upload-link-list";
const loadCreateUploadLinkModal = () => import("./create-upload-link-modal");

export function UploadLinkListHeader({ state }: { state: UploadLinkListState }) {
  const { activeDataKnown, activeCount, archivedDataKnown, archivedLinks, setIsModalOpen } = state;
  return (
    <WorkspacePageHeader
      title="Group Links"
      description="Create groups for document collection or Excel imports, and manage active, closed, and archived groups."
      icon={Link2}
      accent="emerald"
      context={(
        <>
          <WorkspaceHeaderContext icon={Link2}>
            {activeDataKnown ? activeCount.toLocaleString() : "Unavailable"} collecting now
          </WorkspaceHeaderContext>
          <WorkspaceHeaderContext icon={Archive}>
            {archivedDataKnown ? archivedLinks.length.toLocaleString() : "Unavailable"} archived
          </WorkspaceHeaderContext>
        </>
      )}
      actions={(
        <Button
          onClick={() => setIsModalOpen(true)}
          onMouseEnter={() => void loadCreateUploadLinkModal()}
          onFocus={() => void loadCreateUploadLinkModal()}
          onPointerDown={() => void loadCreateUploadLinkModal()}
          className="bg-white text-[#123f73] shadow-sm hover:bg-emerald-50 active:bg-emerald-100"

        >
          <Link2 className="h-4 w-4" aria-hidden="true" />
          Create Group Link
        </Button>
      )}

    />
  );
}
