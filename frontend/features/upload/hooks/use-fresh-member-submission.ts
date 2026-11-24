"use client";

import { useState } from "react";
import type { FreshCollection } from "../api/fresh-draft.api";
import type { getUploadFlowSettings } from "../services/configured-upload";
import { freshValidation } from "../services/fresh-validation";
import type { FreshDraftState } from "./use-fresh-draft";
import type { FreshProof } from "./use-fresh-contact";

/** Rejected server proofs are invalidated without discarding privately saved fields. */
export function useFreshMemberSubmission(state: FreshDraftState, settings: ReturnType<typeof getUploadFlowSettings>, initial: FreshCollection, uploadBusy: boolean, onComplete: () => void) {
  const [proof, setProof] = useState<FreshProof | null>(null), [error, setError] = useState<string>();
  const [rejectedProof, setRejectedProof] = useState<FreshProof | null>(null);
  const submit = async () => {
    if (uploadBusy) return;
    const invalid = freshValidation(settings, state.payload!, state.draft!);
    setError(invalid ?? undefined); if (invalid) return;
    if (!proof || proof.expiresAt <= Date.now()) { setError("Verify your WhatsApp number before submitting."); return; }
    if (initial.submission_mode === "family" && initial.family_member_index === 0) state.collection({
      family_head_name: [state.payload!.passport_fields.given_names, state.payload!.passport_fields.surname].filter(Boolean).join(" ") || state.payload!.current_details.client_name,
      family_head_email: state.payload!.current_details.client_email, family_head_phone: state.payload!.current_details.client_phone,
    });
    try { await state.complete(proof.id); onComplete(); } catch (cause) {
      if (cause && typeof cause === "object" && "code" in cause
        && (cause.code === "verification_failed" || cause.code === "CONTACT_VERIFICATION_REQUIRED")) {
        setRejectedProof(proof); setProof(null);
      }
      // The hook presents the authoritative error and retains the submission key.
    }
  };
  return { proof, setProof, rejectedProof, error, submit };
}
