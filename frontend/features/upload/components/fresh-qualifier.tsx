"use client";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { DraftQualifierInputs } from "../services/draft-input-contract";
import { useFreshQualifier } from "../hooks/use-fresh-qualifier";
import { RelationQualifierStep } from "./relation-qualifier-step";
import { SavedQualifierChoice } from "./saved-qualifier-choice";

export function FreshQualifier({ state, group }: { state: DraftQualifierInputs; group: UploadLinkResponse }) {
  const choice = useFreshQualifier(state, group);
  if (choice.saved) {
    return <SavedQualifierChoice loading={choice.loading} disabled={choice.busy}
      error={choice.error} onEdit={choice.edit} />;
  }
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      {choice.error && <p role="alert" className="mb-3 text-sm text-amber-800">{choice.error}</p>}
      <RelationQualifierStep {...choice.step} />
    </div>
  );
}
