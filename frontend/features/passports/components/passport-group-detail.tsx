"use client";
import { PassportGroupDialogs } from "./passport-group-dialogs";
import { PassportGroupHeaderPanel } from "./passport-group-header-panel";
import { PassportGroupImportPanel } from "./passport-group-import-panel";
import { PassportGroupOverviewPanel } from "./passport-group-overview-panel";
import { PassportGroupRosterPanel } from "./passport-group-roster-panel";
import { PassportGroupSelectionToolbar } from "./passport-group-selection-toolbar";
import { usePassportGroupController } from "./use-passport-group-controller";

export function PassportGroupDetail({ groupId }: { groupId: string }) {
  const controller = usePassportGroupController({ groupId });
  return (
    <div className="flex flex-col gap-5">
      <PassportGroupHeaderPanel {...controller} />
      <PassportGroupOverviewPanel {...controller} />
      <PassportGroupImportPanel {...controller} />
      <PassportGroupSelectionToolbar {...controller} />
      <PassportGroupRosterPanel {...controller} />
      <PassportGroupDialogs {...controller} />
    </div>
  );
}
