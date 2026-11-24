"use client";

import dynamic from "next/dynamic";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import type { PassportListModel } from "./use-passport-list";

type Props = Pick<
  PassportListModel,
  | "selectedGroups"
  | "setSelectedGroups"
  | "exportSelected"
  | "isExportDialogOpen"
  | "setIsExportDialogOpen"
>;

const loadSelectedGroupsExportDialog = () =>
  import("./passport-selected-groups-export-dialog");

const PassportSelectedGroupsExportDialog = dynamic(
  () => import("./passport-selected-groups-export-dialog").then(
    (module) => module.PassportSelectedGroupsExportDialog,
  ),
  { loading: () => null },
);

export function PassportListExportControls({
  selectedGroups,
  setSelectedGroups,
  exportSelected,
  isExportDialogOpen,
  setIsExportDialogOpen,
}: Props) {
  return (
    <>
      {selectedGroups.length > 0 && (
        <div className="flex flex-col gap-3 border-b border-blue-100 bg-blue-50/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <p className="text-sm font-medium text-blue-900" aria-live="polite">
            {selectedGroups.length.toLocaleString()} group{selectedGroups.length === 1 ? "" : "s"} selected for export
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              isLoading={exportSelected.isPending}
              onMouseEnter={() => void loadSelectedGroupsExportDialog()}
              onFocus={() => void loadSelectedGroupsExportDialog()}
              onPointerDown={() => void loadSelectedGroupsExportDialog()}
              onClick={() => {
                exportSelected.reset();
                setIsExportDialogOpen(true);
              }}
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              Export Selected
            </Button>
            <Button type="button" variant="ghost" onClick={() => setSelectedGroups([])}>
              Clear selection
            </Button>
          </div>
        </div>
      )}
      {isExportDialogOpen && selectedGroups.length > 0 && (
        <PassportSelectedGroupsExportDialog
          groupIds={selectedGroups}
          isDownloading={exportSelected.isPending}
          hasDownloadError={exportSelected.isError && !isDownloadCancelled(exportSelected.error)}
          onClose={() => {
            if (!exportSelected.isPending) {
              setIsExportDialogOpen(false);
              exportSelected.reset();
            }
          }}
          onDownload={async ({ supplementalFields, groupByField }) => {
            await exportSelected.mutateAsync({
              groupIds: selectedGroups,
              supplementalFields,
              groupByField,
            });
            setIsExportDialogOpen(false);
          }}
        />
      )}
    </>
  );
}
