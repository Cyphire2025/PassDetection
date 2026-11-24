import { useEffect, useId, useRef, useState } from "react";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { PassportGroupExportMode } from "../api/passports.api";
import { usePassportGroupExportHistory, usePassportGroupExportFields, usePassportGroupExportHistoryDetail } from "../hooks/use-passports";
import type { PassportExportDialogProps } from "./passport-export-dialog";

export function usePassportExportDialog({
  groupId,
  kind,
  isDownloading,
  onClose,
  onDownload,
}: PassportExportDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement | null>(null);
  const downloadStartedRef = useRef(false);
  const [mode, setMode] = useState<PassportGroupExportMode>("all");
  const [historyPage, setHistoryPage] = useState(1);
  const [baselineExportId, setBaselineExportId] = useState<string>();
  const [detailHistoryId, setDetailHistoryId] = useState<string>();
  const [detailPage, setDetailPage] = useState(1);
  const [isStartingDownload, setIsStartingDownload] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [groupByField, setGroupByField] = useState("");
  const [agencyMatchField, setAgencyMatchField] = useState("");
  const fieldsInitializedRef = useRef(false);
  const history = usePassportGroupExportHistory(groupId, kind, historyPage);
  const historyDetail = usePassportGroupExportHistoryDetail(
    groupId,
    detailHistoryId,
    detailPage,
  );
  const isImages = kind === "passport_images";
  const exportFields = usePassportGroupExportFields(groupId, !isImages);
  const isBusy = isDownloading || isStartingDownload;
  const selectedBaseline = history.data?.items.find(
    (item) => item.id === baselineExportId,
  );
  useEffect(() => {
    if (!exportFields.data || fieldsInitializedRef.current) return;
    fieldsInitializedRef.current = true;
    setSelectedFields(exportFields.data.default_selected_fields);
    setGroupByField(exportFields.data.default_group_by_field ?? "");
  }, [exportFields.data]);
  const handleKeyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !isBusy, onClose });
  const canDownload = (
    !isBusy
    && !history.isLoading
    && (
      mode === "all"
      || Boolean(
        baselineExportId
        && selectedBaseline
        && selectedBaseline.compatible
        && (selectedBaseline.new_submission_count + (selectedBaseline.changed_submission_count ?? 0) + (selectedBaseline.removed_submission_count ?? 0)) > 0,
      )
    )
  );
  const isExcelFieldStep = !isImages && step === 2;
  return {
    isImages,
    titleId,
    descriptionId,
    isExcelFieldStep,
    isBusy,
    onClose,
    dialogRef,
    handleKeyDown,
    exportFields,
    selectedFields,
    setSelectedFields,
    groupByField,
    setGroupByField,
    agencyMatchField,
    setAgencyMatchField,
    history,
    kind,
    mode,
    setMode,
    baselineExportId,
    setBaselineExportId,
    setDetailPage,
    setDetailHistoryId,
    detailHistoryId,
    historyDetail,
    detailPage,
    historyPage,
    setHistoryPage,
    setStep,
    canDownload,
    step,
    downloadStartedRef,
    isDownloading,
    setIsStartingDownload,
    onDownload
  };
}

export type PassportExportDialogState = ReturnType<typeof usePassportExportDialog>;
