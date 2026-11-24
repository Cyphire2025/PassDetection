"use client";

import { useCallback, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type { PassportGroupSubmissionsView } from "../api/passports.api";
import { MAX_BULK_SELECTION } from "./passport-group-bindings";

interface SelectionState {
  selectedPassports: string[];
  selectedPassportIdSet: Set<string>;
  selectedPassportRevisions: Record<string, number>;
  selectionPreset: string;
  customSelectionCount: string;
  bulkDeleteFeedback: { tone: "success" | "warning" | "error"; message: string } | null;
}

function useSelectionField<K extends keyof SelectionState>(
  setSelection: Dispatch<SetStateAction<SelectionState>>,
  key: K,
): Dispatch<SetStateAction<SelectionState[K]>> {
  return useCallback((update) => {
    setSelection((current) => {
      const next = {
        ...current,
        [key]: typeof update === "function" ? update(current[key]) : update,
      };
      if (key === "selectedPassports") next.selectedPassportIdSet = new Set(next.selectedPassports);
      return next;
    });
  }, [key, setSelection]);
}

export function usePassportGroupSelection(
  submissionsView: PassportGroupSubmissionsView | undefined,
  closeMenu: () => void,
) {
  // IDs and revisions change atomically, including several actions in one turn.
  const [selection, setSelection] = useState<SelectionState>({
    selectedPassports: [], selectedPassportIdSet: new Set(), selectedPassportRevisions: {}, selectionPreset: "",
    customSelectionCount: "", bulkDeleteFeedback: null,
  });
  const { customSelectionCount } = selection;
  const setSelectedPassports = useSelectionField(setSelection, "selectedPassports");
  const setSelectedPassportRevisions = useSelectionField(setSelection, "selectedPassportRevisions");
  const setSelectionPreset = useSelectionField(setSelection, "selectionPreset");
  const setCustomSelectionCount = useSelectionField(setSelection, "customSelectionCount");
  const setBulkDeleteFeedback = useSelectionField(setSelection, "bulkDeleteFeedback");
  const selectionRevisionById = useMemo(() => {
    const revisions = new Map(
      (submissionsView?.ordered_selection_snapshot ?? []).map((snapshot) => [
        snapshot.submission_id, snapshot.extraction_revision,
      ]),
    );
    for (const submission of submissionsView?.items ?? []) {
      revisions.set(submission.id, submission.extraction_revision);
    }
    return revisions;
  }, [submissionsView?.items, submissionsView?.ordered_selection_snapshot]);
  const maxBulkSelectionCount = Math.min(MAX_BULK_SELECTION, submissionsView?.total ?? 0);
  const parsedCustomSelectionCount = Number(customSelectionCount);
  const customSelectionIsValid = Number.isInteger(parsedCustomSelectionCount)
    && parsedCustomSelectionCount >= 1 && parsedCustomSelectionCount <= maxBulkSelectionCount;

  const resetBulkSelection = () => {
    setSelection((current) => ({
      ...current, selectedPassports: [], selectedPassportIdSet: new Set(), selectedPassportRevisions: {},
      selectionPreset: "", customSelectionCount: "",
    }));
    closeMenu();
  };
  const togglePassport = (passportId: string) => {
    setSelection((current) => {
      if (current.selectedPassportIdSet.has(passportId)) {
        const revisions = { ...current.selectedPassportRevisions };
        delete revisions[passportId];
        const selectedPassportIdSet = new Set(current.selectedPassportIdSet);
        selectedPassportIdSet.delete(passportId);
        return {
          ...current, selectionPreset: "",
          selectedPassportIdSet,
          selectedPassports: current.selectedPassports.filter((id) => id !== passportId),
          selectedPassportRevisions: revisions,
        };
      }
      const revision = selectionRevisionById.get(passportId);
      if (revision === undefined) return { ...current, selectionPreset: "" };
      if (current.selectedPassports.length >= MAX_BULK_SELECTION) {
        return { ...current, selectionPreset: "", bulkDeleteFeedback: {
          tone: "warning", message: `Select at most ${MAX_BULK_SELECTION.toLocaleString()} submissions at a time.`,
        } };
      }
      return {
        ...current, selectionPreset: "",
        selectedPassportIdSet: new Set([...current.selectedPassportIdSet, passportId]),
        selectedPassports: [...current.selectedPassports, passportId],
        selectedPassportRevisions: { ...current.selectedPassportRevisions, [passportId]: revision },
      };
    });
  };
  const selectFirstPassports = (requestedCount: number) => {
    const orderedIds = submissionsView?.ordered_submission_ids ?? [];
    const boundedCount = Math.min(Math.max(0, requestedCount), orderedIds.length, MAX_BULK_SELECTION);
    const selectedIds = orderedIds.slice(0, boundedCount);
    setSelection((current) => {
      const selectedPassports = Array.from(new Set([...current.selectedPassports, ...selectedIds])).slice(0, MAX_BULK_SELECTION);
      const selectedPassportIdSet = new Set(selectedPassports);
      return {
        ...current,
        selectedPassports,
        selectedPassportIdSet,
        selectedPassportRevisions: {
          ...Object.fromEntries(Object.entries(current.selectedPassportRevisions)
            .filter(([submissionId]) => selectedPassportIdSet.has(submissionId))),
          ...Object.fromEntries(selectedIds.flatMap((submissionId) => {
            const revision = selectionRevisionById.get(submissionId);
            return revision === undefined || !selectedPassportIdSet.has(submissionId)
              ? [] : [[submissionId, revision]];
          })),
        },
      };
    });
    closeMenu();
  };
  const handleSelectionPreset = (preset: string) => {
    setSelectionPreset(preset);
    if (preset === "custom") {
      setCustomSelectionCount((current) => current || "1");
      return;
    }
    if (preset === "all") {
      selectFirstPassports(submissionsView?.ordered_submission_ids.length ?? 0);
      return;
    }
    const count = Number.parseInt(preset, 10);
    if (Number.isFinite(count)) selectFirstPassports(count);
  };

  return {
    ...selection, parsedCustomSelectionCount, customSelectionIsValid,
    setSelectedPassports, setSelectedPassportRevisions, setSelectionPreset,
    setCustomSelectionCount, setBulkDeleteFeedback, resetBulkSelection,
    togglePassport, selectFirstPassports, handleSelectionPreset,
  };
}
