export interface FreshMemberResume { sessionId: string; submissionKey: string; completed: boolean }
export interface FreshResume { mode: "single" | "family"; familyGroupId: string; active: number; members: FreshMemberResume[] }
export interface DraftResume { version: 1; expiresAt: number; mode: "returning" | "new"; submissionKey: string; fresh?: FreshResume }

const MAX_RESUME_LENGTH = 32_768;
const MAX_OPAQUE_ID_LENGTH = 128;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= MAX_OPAQUE_ID_LENGTH;
}

function parseMember(value: unknown): FreshMemberResume | null {
  if (!isRecord(value) || !isOpaqueId(value.sessionId) || !isOpaqueId(value.submissionKey) || typeof value.completed !== "boolean") return null;
  return { sessionId: value.sessionId, submissionKey: value.submissionKey, completed: value.completed };
}

function parseFresh(value: unknown): FreshResume | null {
  if (!isRecord(value) || (value.mode !== "single" && value.mode !== "family") || !isOpaqueId(value.familyGroupId)) return null;
  if (!Array.isArray(value.members) || value.members.length < 1 || value.members.length > 20) return null;
  if (typeof value.active !== "number" || !Number.isInteger(value.active) || value.active < 0 || value.active >= value.members.length) return null;
  const members: FreshMemberResume[] = [];
  for (const candidate of value.members) {
    const member = parseMember(candidate);
    if (!member) return null;
    members.push(member);
  }
  return { mode: value.mode, familyGroupId: value.familyGroupId, active: value.active, members };
}

/** Read navigation metadata only; never restore personal fields from browser storage. */
export function parseDraftResume(text: string | null): DraftResume | null {
  if (!text || text.length > MAX_RESUME_LENGTH) return null;
  try {
    const value: unknown = JSON.parse(text);
    if (!isRecord(value) || value.version !== 1 || (value.mode !== "returning" && value.mode !== "new")) return null;
    if (typeof value.expiresAt !== "number" || !Number.isFinite(value.expiresAt) || value.expiresAt <= Date.now()) return null;
    if (!isOpaqueId(value.submissionKey)) return null;
    const fresh = value.fresh === undefined ? undefined : parseFresh(value.fresh);
    if (fresh === null) return null;
    return { version: 1, expiresAt: value.expiresAt, mode: value.mode, submissionKey: value.submissionKey, ...(fresh ? { fresh } : {}) };
  } catch { return null; }
}
