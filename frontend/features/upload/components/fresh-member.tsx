"use client";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { FreshResume } from "@/features/travellers/services/draft-resume";
import { freshDraftApi, type FreshCollection } from "../api/fresh-draft.api";
import { freshError } from "../services/fresh-draft-state";
import { CenteredLoader } from "./upload-flow-shell";
import { FreshMemberForm } from "./fresh-member-form";

export function FreshMember({ token, group, resume, onStarted, onComplete, onBack }: { token: string; group: UploadLinkResponse; resume: FreshResume; onStarted: (expires: string) => void; onComplete: () => void; onBack: () => void }) {
  const [head, setHead] = useState<Pick<FreshCollection, "family_head_name" | "family_head_email" | "family_head_phone">>();
  const [error, setError] = useState<string>(), [attempt, setAttempt] = useState(0);
  const headSession = resume.members[0].sessionId;
  useEffect(() => {
    if (resume.active === 0) return;
    const controller = new AbortController();
    void freshDraftApi(token, headSession).start(controller.signal).then((draft) => {
      if (controller.signal.aborted) return;
      if (draft.status !== "submitted") throw new Error("Submit the head of family’s details before adding another member.");
      const fields = draft.passport_fields;
      setHead({ family_head_name: [fields.given_names, fields.surname].filter(Boolean).join(" ") || draft.current_details.client_name, family_head_email: draft.current_details.client_email, family_head_phone: draft.current_details.client_phone });
    }).catch((cause) => { if (!controller.signal.aborted) setError(freshError(cause)); });
    return () => controller.abort();
  }, [token, headSession, resume.active, attempt]);
  if (resume.active > 0 && !head) return <><Button type="button" variant="ghost" onClick={onBack}>Back</Button>{error ? <div role="alert" className="rounded-xl bg-white p-5 text-red-700">{error}<Button type="button" variant="secondary" className="ml-3" onClick={() => { setError(undefined); setAttempt((value) => value + 1); }}>Retry</Button></div> : <CenteredLoader />}</>;
  const initial: FreshCollection = { acquisition_mode: group.allow_files_from_device === false ? "camera" : "file", submission_mode: resume.mode, ...(resume.mode === "family" ? { family_group_id: resume.familyGroupId, family_member_index: resume.active, family_relation: resume.active === 0 ? "Head" : "", ...head } : {}) };
  return <FreshMemberForm token={token} group={group} member={resume.members[resume.active]} initial={initial} onStarted={onStarted} onComplete={onComplete} onBack={onBack} />;
}
