import type { FamilyMember, FamilyReuseBinding } from "../components/upload-flow.types";
import { isClientSubmissionComplete } from "./upload-flow-helpers";

/** O(1) source equality; a replaced upload or extraction invalidates prior proof. */
export function matchesFamilySource(member: FamilyMember, binding: FamilyReuseBinding): boolean {
  return member.localId === binding.localId && member.submission?.id === binding.sourceSubmissionId
    && member.submission.extraction_revision === binding.extractionRevision && member.uploadIdempotencyKey === binding.uploadSessionId;
}

export function isFamilyMemberSubmitted(member: FamilyMember): boolean {
  return Boolean(member.submission && isClientSubmissionComplete(member.submission))
    || Boolean(member.reuseCompletion && matchesFamilySource(member, member.reuseCompletion.binding));
}
