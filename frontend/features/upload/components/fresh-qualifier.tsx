"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { DraftQualifierInputs } from "../services/draft-input-contract";
import { getUploadFlowSettings } from "../services/configured-upload";
import { buildQualifierSelectionRequest, type QualifierPath } from "../services/relation-qualifier";
import { RelationQualifierStep } from "./relation-qualifier-step";

export function FreshQualifier({ state, group }: { state: DraftQualifierInputs; group: UploadLinkResponse }) {
  const [path, setPath] = useState<QualifierPath>(null), [relation, setRelation] = useState(""), [other, setOther] = useState("");
  const [editing, setEditing] = useState(false);
  const config = getUploadFlowSettings(group).uploadConfig;
  if (state.payload?.collection?.qualifier_selection_token && !editing) return <div className="flex items-center justify-between gap-3 rounded-xl bg-blue-50 p-3 text-sm text-blue-900"><span>Qualifier relationship saved</span><Button type="button" variant="secondary" onClick={() => setEditing(true)}>Change</Button></div>;
  const save = () => {
    const choice = buildQualifierSelectionRequest(path, relation, group.qualifier_relation_options, other, { listEnabled: config.qualifier_relation_list_enabled, otherEnabled: config.qualifier_relation_other_enabled });
    if (!choice) return;
    void state.serialized(async (signal) => {
      const result = await state.api.qualifier(choice, signal);
      state.collection({ qualifier_selection_token: result.selection_token }); setEditing(false);
    }, true).catch(() => undefined);
  };
  return <div className="rounded-2xl border border-slate-200 bg-white p-5"><RelationQualifierStep path={path} relationCode={relation} otherRelation={other} listEnabled={config.qualifier_relation_list_enabled} otherEnabled={config.qualifier_relation_other_enabled} options={group.qualifier_relation_options} isSaving={state.pending} onPathChange={setPath} onRelationChange={setRelation} onOtherRelationChange={setOther} onContinue={save} /></div>;
}
