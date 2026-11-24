import { ChevronRight, Download } from "lucide-react";
import { Button } from "@/components/ui";
import type { PassportExportDialogState } from "./use-passport-export-dialog";

export function PassportExportFooter({ state }: { state: PassportExportDialogState }) {
  const {
    isBusy,
    isExcelFieldStep,
    setStep,
    onClose,
    canDownload,
    exportFields,
    isImages,
    step,
    downloadStartedRef,
    isDownloading,
    setIsStartingDownload,
    onDownload,
    mode,
    baselineExportId,
    selectedFields,
    groupByField,
    agencyMatchField
  } = state;
  return (
    <div
      className="flex flex-col-reverse gap-2 border-t border-slate-200 bg-slate-50 px-5 py-4 sm:flex-row sm:justify-end sm:px-6"
    >
      <Button
        type="button"
        variant="secondary"
        disabled={isBusy}
        onClick={() => {
          if (isExcelFieldStep) {
            setStep(1);
          } else {
            onClose();
          }
        }}
      >
        {isExcelFieldStep ? "Back" : "Cancel"}
      </Button>
      <Button
        type="button"
        disabled={
          !canDownload
          || (isExcelFieldStep && (exportFields.isLoading || Boolean(exportFields.error)))
        }
        isLoading={isBusy}
        onClick={async () => {
          if (!isImages && step === 1) {
            setStep(2);
            return;
          }
          if (downloadStartedRef.current || isDownloading) return;
          downloadStartedRef.current = true;
          setIsStartingDownload(true);
          try {
            await onDownload({
              mode,
              ...(mode === "incremental" && baselineExportId
                ? { baselineExportId }
                : {}),
              ...(!isImages ? {
                supplementalFields: selectedFields,
                groupByField: groupByField || "none",
                agencyMatchField: agencyMatchField || undefined,
              } : {}),
            });
          } finally {
            downloadStartedRef.current = false;
            setIsStartingDownload(false);
          }
        }}
      >
        {!isImages && step === 1 ? (
          <>
            Next
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </>
        ) : (
          <>
            <Download className="h-4 w-4" aria-hidden="true" />
            {mode === "all"
              ? (isImages ? "Download all" : "Download Excel")
              : "Download changes"}
          </>
        )}
      </Button>
    </div>
  );
}
