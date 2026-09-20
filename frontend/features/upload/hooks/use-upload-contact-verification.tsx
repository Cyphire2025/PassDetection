import { useEffect, useState } from "react";
import type { PassportSubmission } from "@/types/passport.types";
import { normalizePhoneNumber } from "@/lib/utils/phone-number";
import { UploadContactVerification, validContactEmail, type ContactVerification } from "../components/upload-contact-verification";
import type { FamilyMember, UploadFlowStep } from "../components/upload-flow.types";
import { isClientSubmissionComplete } from "../services/upload-flow-helpers";

export function isContactVerificationError(error: unknown) {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "CONTACT_VERIFICATION_REQUIRED");
}

interface Contact {
  submissionId: string;
  sessionId: string;
  name: string;
  email: string;
  phone: string;
  familyIndex?: number;
}

interface Props {
  token: string;
  step: UploadFlowStep;
  submission: PassportSubmission | null;
  sessionId: string;
  name: string;
  email: string;
  phone: string;
  familyMembers: FamilyMember[];
  onSingleContact: (email: string, phone: string) => void;
  onFamilyContact: (index: number, email: string, phone: string) => void;
  onBack: () => void;
}

export function useUploadContactVerification(props: Props) {
  const [proofs, setProofs] = useState<Record<string, ContactVerification>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const nextExpiry = Math.min(...Object.values(proofs).map((proof) => proof.expiresAt).filter((expiresAt) => expiresAt > Date.now()));
    if (!Number.isFinite(nextExpiry)) return;
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(0, nextExpiry - Date.now()));
    return () => window.clearTimeout(timer);
  }, [proofs, now]);

  const getProof = (submissionId: string | undefined, sessionId: string, email: string, phone: string): ContactVerification | null => {
    if (!submissionId || !validContactEmail(email)) return null;
    const proof = proofs[submissionId];
    return proof && proof.sessionId === sessionId && proof.email === email.trim() && proof.phone === normalizePhoneNumber(phone) && proof.expiresAt > now ? proof : null;
  };
  const invalidate = (submissionId: string) => setProofs((current) => {
    const next = { ...current };
    delete next[submissionId];
    return next;
  });
  const contacts: Contact[] = [];
  if (props.step === "REVIEW" && props.submission) {
    contacts.push({ submissionId: props.submission.id, sessionId: props.sessionId, name: props.name, email: props.email, phone: props.phone });
  } else if (props.step === "FAMILY_REVIEW") {
    props.familyMembers.forEach((member, familyIndex) => {
      if (member.submission && !isClientSubmissionComplete(member.submission)) contacts.push({ submissionId: member.submission.id, sessionId: member.uploadIdempotencyKey, name: member.name, email: member.email, phone: member.phone, familyIndex });
    });
  }
  const active = contacts.find((contact) => contact.submissionId === editing)
    ?? contacts.find((contact) => !getProof(contact.submissionId, contact.sessionId, contact.email, contact.phone));
  const page = active ? <UploadContactVerification
    key={`${props.token}:${active.submissionId}:${active.sessionId}`}
    token={props.token} submissionId={active.submissionId} sessionId={active.sessionId}
    name={active.name} email={active.email} phone={active.phone}
    progress={active.familyIndex !== undefined ? `Family member ${active.familyIndex + 1} of ${props.familyMembers.length}` : undefined}
    verification={getProof(active.submissionId, active.sessionId, active.email, active.phone)}
    onContactChange={(email, phone) => {
      invalidate(active.submissionId);
      if (active.familyIndex === undefined) props.onSingleContact(email, phone);
      else props.onFamilyContact(active.familyIndex, email, phone);
    }}
    onVerified={(verification) => {
      setProofs((current) => ({ ...current, [active.submissionId]: verification }));
      setEditing(null);
    }}
    onBack={props.onBack}
  /> : null;
  return { page, getProof, edit: setEditing, invalidate };
}
