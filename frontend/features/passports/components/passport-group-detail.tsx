"use client";
import { DocumentThumbnailCacheProvider } from "./document-thumbnail-cache-provider";
import { PassportDisplayNameDialog } from "./passport-display-name-dialog";
import { PassportGroupDialogs } from "./passport-group-dialogs";
import { PassportGroupHeaderPanel } from "./passport-group-header-panel";
import { PassportGroupReadiness } from "./passport-group-readiness";
import { GroupWorkspaceBackground } from "@/features/branding/components/group-workspace-background";
import { GroupBanner } from "@/features/branding/components/group-banner";
import { PassportGroupImportPanel } from "./passport-group-import-panel";
import { PassportGroupOverviewPanel } from "./passport-group-overview-panel";
import { PassportGroupRosterPanel } from "./passport-group-roster-panel";
import { PassportGroupSelectionToolbar } from "./passport-group-selection-toolbar";
import { usePassportGroupController } from "./use-passport-group-controller";

export function PassportGroupDetail({ groupId }: { groupId: string }) {
  const controller = usePassportGroupController({ groupId });
  return (
    <DocumentThumbnailCacheProvider key={`${groupId}:${controller.page}`}>
      <GroupWorkspaceBackground src={controller.groupDetails?.background_url}>
        <GroupBanner src={controller.groupDetails?.banner_url}>
          <PassportGroupHeaderPanel {...controller} />
          <PassportGroupReadiness {...controller} />
        </GroupBanner>
        <PassportGroupOverviewPanel {...controller} />
        <PassportGroupImportPanel {...controller} />
        <PassportGroupSelectionToolbar {...controller} />
        <PassportGroupRosterPanel {...controller} />
        <PassportGroupDialogs {...controller} />
        {controller.displayNameEditorId && controller.canEditDisplayName && (
          <PassportDisplayNameDialog key={controller.displayNameEditorId} id={controller.displayNameEditorId} groupId={groupId}
            onClose={() => controller.setDisplayNameEditorId(null)} />
        )}
      </GroupWorkspaceBackground>
    </DocumentThumbnailCacheProvider>
  );
}
