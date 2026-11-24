"use client";
import { useEffect, useRef, useState } from "react";
import { uploadLinksApi, type QualifierSelectionState, type UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { DraftQualifierInputs } from "../services/draft-input-contract";
import { getUploadFlowSettings } from "../services/configured-upload";
import { buildQualifierSelectionRequest, type QualifierPath } from "../services/relation-qualifier";

type Choice = { path: QualifierPath; relation: string; other: string };
const emptyChoice: Choice = { path: null, relation: "", other: "" };

function restoredChoice(saved: QualifierSelectionState): Choice {
  if (saved.status !== "active") return emptyChoice;
  if (saved.is_self) return { path: "self", relation: "", other: "" };
  if (saved.relation_code === "other") return { path: "other", relation: "", other: saved.relation_label };
  return { path: "relation", relation: saved.relation_code ?? "", other: "" };
}

/** Restore only on an explicit edit; aborted or stale reads never replace the current choice. */
export function useFreshQualifier(state: DraftQualifierInputs, group: UploadLinkResponse) {
  const [choice, setChoice] = useState<Choice>(emptyChoice);
  const [editing, setEditing] = useState(false);
  const [loadingKey, setLoadingKey] = useState<string>();
  const [error, setError] = useState<string>();
  const restoring = useRef<AbortController | null>(null);
  const selectionToken = state.payload?.collection?.qualifier_selection_token;
  const selectionKey = `${group.token}:${selectionToken ?? ""}`;
  const loading = loadingKey === selectionKey;
  const config = getUploadFlowSettings(group).uploadConfig;
  useEffect(() => () => {
    restoring.current?.abort();
    restoring.current = null;
  }, [selectionToken, group.token]);

  const edit = async () => {
    if (!selectionToken || restoring.current) return;
    const controller = new AbortController();
    restoring.current = controller;
    setLoadingKey(selectionKey);
    setError(undefined);
    try {
      const saved = await uploadLinksApi.getQualifierSelection(group.token, selectionToken, controller.signal);
      if (controller.signal.aborted) return;
      setChoice(restoredChoice(saved));
      if (saved.status !== "active") {
        state.collection({ qualifier_selection_token: null });
        setError("Your previous relationship choice is no longer active. Please choose again.");
      }
      setEditing(true);
    } catch {
      if (!controller.signal.aborted) {
        setError("Your saved relationship could not be loaded. Please try Change again; your choice has been kept.");
      }
    } finally {
      if (restoring.current === controller) {
        restoring.current = null;
        setLoadingKey(undefined);
      }
    }
  };
  const save = () => {
    const request = buildQualifierSelectionRequest(choice.path, choice.relation, group.qualifier_relation_options,
      choice.other, { listEnabled: config.qualifier_relation_list_enabled, otherEnabled: config.qualifier_relation_other_enabled });
    if (!request) return;
    void state.serialized(async (signal) => {
      const result = await state.api.qualifier(request, signal);
      if (signal.aborted) return;
      state.collection({ qualifier_selection_token: result.selection_token });
      setEditing(false);
      setError(undefined);
    }, true).catch(() => undefined);
  };
  return {
    saved: Boolean(selectionToken && !editing), loading, busy: state.pending || loading, error,
    edit: () => { void edit(); },
    step: {
      path: choice.path, relationCode: choice.relation, otherRelation: choice.other,
      listEnabled: config.qualifier_relation_list_enabled, otherEnabled: config.qualifier_relation_other_enabled,
      options: group.qualifier_relation_options, isSaving: state.pending,
      onPathChange: (path: Exclude<QualifierPath, null>) => setChoice(current => ({ ...current, path })),
      onRelationChange: (relation: string) => setChoice(current => ({ ...current, relation })),
      onOtherRelationChange: (other: string) => setChoice(current => ({ ...current, other })),
      onContinue: save,
    },
  };
}
