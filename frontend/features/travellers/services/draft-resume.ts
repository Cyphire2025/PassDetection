import { parseDraftResume, type DraftResume, type FreshResume } from "./draft-resume-parser";
export { parseDraftResume, type DraftResume, type FreshMemberResume, type FreshResume } from "./draft-resume-parser";
const key = (token: string) => `gc.traveller.draft.v1:${token}`;
export function draftResumeText(token: string): string | null {
  try { return localStorage.getItem(key(token)); } catch { return null; }
}
export function subscribeDraftResume(callback: () => void) {
  window.addEventListener("storage", callback); window.addEventListener("traveller-draft-change", callback);
  return () => { window.removeEventListener("storage", callback); window.removeEventListener("traveller-draft-change", callback); };
}
/** Only expiry/navigation/idempotency metadata. Never store passport data here. */
export function readDraftResume(token: string): DraftResume | null {
  try {
    const value = parseDraftResume(draftResumeText(token));
    if (value) return value;
    localStorage.removeItem(key(token));
  } catch { /* Private browsing/storage restrictions do not block submission. */ }
  return null;
}
export function saveDraftResume(token: string, expiresAt: string, mode: DraftResume["mode"]): DraftResume {
  const existing = readDraftResume(token);
  const value: DraftResume = { version: 1, expiresAt: Date.parse(expiresAt), mode, submissionKey: existing?.submissionKey ?? crypto.randomUUID(), ...(mode === "new" && existing?.fresh ? { fresh: existing.fresh } : {}) };
  try { localStorage.setItem(key(token), JSON.stringify(value)); window.dispatchEvent(new Event("traveller-draft-change")); } catch { /* Cookie-backed draft remains usable. */ }
  return value;
}
export function clearDraftResume(token: string) { try { localStorage.removeItem(key(token)); window.dispatchEvent(new Event("traveller-draft-change")); } catch { /* No retained personal data. */ } }

/** Family navigation only; names, contact details and documents stay server-side. */
export function saveFreshResume(token: string, fresh: FreshResume, expiresAt?: string) {
  const existing = readDraftResume(token);
  const expires = existing?.mode === "new" ? existing.expiresAt : Date.now() + 86_400_000;
  const metadata: FreshResume = { mode: fresh.mode, familyGroupId: fresh.familyGroupId, active: fresh.active, members: fresh.members.map(({ sessionId, submissionKey, completed }) => ({ sessionId, submissionKey, completed })) };
  const value: DraftResume = { version: 1, mode: "new", expiresAt: expiresAt ? Math.min(Date.parse(expiresAt), expires) : expires, submissionKey: existing?.submissionKey ?? crypto.randomUUID(), fresh: metadata };
  try { localStorage.setItem(key(token), JSON.stringify(value)); window.dispatchEvent(new Event("traveller-draft-change")); } catch { /* Session remains available in memory. */ }
  return value;
}
