"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { returningApi } from "@/features/travellers/api/returning.api";
import type { CompletionResult, ReplacementRequest } from "@/features/travellers/types";
import type { FamilyMember, FamilyReuseBinding } from "../components/upload-flow.types";
import type { FamilyMemberUpdate } from "../services/family-upload-state";
import { matchesFamilySource } from "../services/family-returning";
import { CenteredLoader } from "../components/upload-flow-shell";

const ReturningFlow = dynamic(() => import("@/features/travellers/components/returning-flow").then((module) => module.ReturningFlow), { loading: () => <CenteredLoader /> });
type Selection = FamilyReuseBinding & { token: string; replacementKey: string; generation: number };

/** Only the captured member's owned extraction can receive a server-verified result. */
export function useReturningFamily({ token, group, members, updateMember }: { token: string; group: UploadLinkResponse | undefined; members: FamilyMember[]; updateMember: (index: number, update: FamilyMemberUpdate) => void }) {
  const [selected, setSelected] = useState<Selection>();
  const [error, setError] = useState<string>();
  const operation = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; operation.current?.abort(); }, [token]);
  const index = selected?.token === token ? members.findIndex((member) => matchesFamilySource(member, selected)) : -1;
  const open = (member: FamilyMember) => {
    if (!member.submission || member.submission.extraction_revision < 1) return;
    operation.current?.abort(); operation.current = null; setError(undefined);
    setSelected({ token, localId: member.localId, sourceSubmissionId: member.submission.id, extractionRevision: member.submission.extraction_revision, uploadSessionId: member.uploadIdempotencyKey, replacementKey: crypto.randomUUID(), generation: ++generation.current });
  };
  const close = () => { generation.current++; operation.current?.abort(); operation.current = null; setSelected(undefined); setError(undefined); };
  const complete = (result: CompletionResult) => {
    if (!selected || selected.generation !== generation.current || index < 0 || !result.source_submission_id) return;
    const boundResult = { ...result, source_submission_id: result.source_submission_id };
    updateMember(index, (current) => matchesFamilySource(current, selected) ? { reuseCompletion: { binding: selected, result: boundResult } } : {});
  };
  const replace = async (request: ReplacementRequest) => {
    if (!selected || index < 0 || operation.current) return;
    const controller = new AbortController(); operation.current = controller; setError(undefined);
    try {
      await returningApi.replacement({ source_submission_id: selected.sourceSubmissionId, expected_extraction_revision: selected.extractionRevision, review_version: request.reviewVersion, change_kind: request.changeKind, idempotency_key: selected.replacementKey }, selected.uploadSessionId, controller.signal);
      if (controller.signal.aborted) return;
      updateMember(index, (current) => matchesFamilySource(current, selected) ? { replacementAssociated: selected } : {});
      setSelected(undefined);
    } catch { if (!controller.signal.aborted) setError("This document update could not be linked. Retry, or continue with the current upload."); }
    finally { if (operation.current === controller) operation.current = null; }
  };
  const verificationPage = selected && index >= 0 && group ? <div>{error && <p role="alert" className="bg-red-50 p-4 text-sm text-red-800">{error}</p>}<ReturningFlow key={`${selected.localId}:${selected.sourceSubmissionId}:${selected.extractionRevision}`} token={token} group={group} initialMethod="passport" capabilities={{ enabled: true, code_label: null }} ownedSource={{ source_submission_id: selected.sourceSubmissionId, expected_extraction_revision: selected.extractionRevision, uploadSessionId: selected.uploadSessionId }} onCompleted={complete} onFresh={close} onReplace={(request) => void replace(request)} /></div> : null;
  return { open, verificationPage };
}
