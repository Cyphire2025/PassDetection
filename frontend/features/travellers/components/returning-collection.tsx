"use client";
import { useMemo, useState } from "react";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { getOrCreatePublicUploadSessionId } from "@/features/passports/api/public-upload-session";
import { FreshDocuments } from "@/features/upload/components/fresh-documents";
import { FreshQualifier } from "@/features/upload/components/fresh-qualifier";
import { getUploadFlowSettings } from "@/features/upload/services/configured-upload";
import { freshDraftApi } from "@/features/upload/api/fresh-draft.api";
import { returningDraftApi } from "../api/returning-draft.api";
import type { useReturningDraft } from "../hooks/use-returning-draft";
import type { ReturningDocument } from "../types";

export function ReturningCollection({ form, group, token, updatesEnabled, qualifier, documents, onChange, onUploadBusyChange }: { form: ReturnType<typeof useReturningDraft>; group?: UploadLinkResponse; token: string; updatesEnabled: boolean; qualifier: boolean; documents: ReturningDocument[]; onChange: () => void; onUploadBusyChange: (busy: boolean) => void }) {
  const [sessionId] = useState(() => getOrCreatePublicUploadSessionId(token));
  const draftId = form.draft?.id;
  const api = useMemo(() => ({ qualifier: freshDraftApi(token, sessionId).qualifier, document: (id: string, signal?: AbortSignal) => returningDraftApi.document(id, draftId!, signal) }), [token, sessionId, draftId]);
  if (!group || !form.draft) return <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">The trip’s document settings could not be loaded. Refresh the link before completing these requirements.</p>;
  const inputs = { ...form, api, collection: (patch: Parameters<typeof form.collection>[0]) => { onChange(); form.collection(patch); }, upload: (side: Parameters<typeof form.upload>[0], file: File) => { onChange(); return form.upload(side, file); } };
  return <section className="space-y-4" aria-label="Additional trip requirements">
    <FreshDocuments state={inputs} settings={getUploadFlowSettings(group)} token={token} sessionId={sessionId} savedDocuments={documents} editableSides={updatesEnabled ? undefined : []} onUploadBusyChange={(busy) => { if (busy) onChange(); onUploadBusyChange(busy); }} />
    {qualifier && <FreshQualifier state={inputs} group={group} />}
  </section>;
}
