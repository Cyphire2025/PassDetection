import { beforeEach, describe, expect, it } from "vitest";
import { parseDraftResume, readDraftResume, saveDraftResume, saveFreshResume } from "./draft-resume";
describe("private draft navigation metadata", () => {
  beforeEach(() => localStorage.clear());
  it("retains returning idempotency and never extends a family past its first deadline", () => {
    const returning = saveDraftResume("trip", new Date(Date.now() + 60_000).toISOString(), "returning");
    expect(saveDraftResume("trip", new Date(Date.now() + 90_000).toISOString(), "returning").submissionKey).toBe(returning.submissionKey);
    const family = { mode: "family" as const, familyGroupId: "family", active: 0, members: [{ sessionId: "member-one", submissionKey: "submit-one", completed: false }] };
    const first = saveFreshResume("new-trip", family, new Date(Date.now() + 60_000).toISOString());
    saveFreshResume("new-trip", family, new Date(Date.now() + 90_000).toISOString());
    expect(readDraftResume("new-trip")?.expiresAt).toBe(first.expiresAt);
  });
  it("allowlists metadata even if caller objects have extra personal fields", () => {
    saveFreshResume("trip", { mode: "single", familyGroupId: "family", active: 0, members: [{ sessionId: "member", submissionKey: "submit", completed: false, passport_number: "SECRET" } as never], client_email: "secret@example.test" } as never);
    expect(localStorage.getItem("gc.traveller.draft.v1:trip")).not.toMatch(/SECRET|secret@example/);
  });
  it("rejects expired or out-of-bounds family navigation", () => {
    expect(parseDraftResume(JSON.stringify({ version: 1, expiresAt: 1, mode: "new", submissionKey: "key" }))).toBeNull();
    expect(parseDraftResume(JSON.stringify({ version: 1, expiresAt: Date.now() + 60_000, mode: "new", submissionKey: "key", fresh: { mode: "family", familyGroupId: "family", active: 20, members: [] } }))).toBeNull();
  });

  it("rejects corrupt, missing, nonfinite or oversized navigation metadata", () => {
    const valid = { version: 1, expiresAt: Date.now() + 60_000, mode: "new", submissionKey: "opaque-key" };
    for (const text of [null, "", "not-json", "{}", JSON.stringify({ ...valid, version: 2 }),
      JSON.stringify({ ...valid, expiresAt: undefined }), JSON.stringify({ ...valid, expiresAt: "future" }),
      JSON.stringify({ ...valid, expiresAt: null }), JSON.stringify({ ...valid, submissionKey: "" }),
      JSON.stringify({ ...valid, submissionKey: "x".repeat(129) }), " ".repeat(32_769)]) {
      expect(parseDraftResume(text)).toBeNull();
    }
  });

  it("reads only bounded opaque identities and navigation, discarding extra personal data", () => {
    const value = { version: 1, expiresAt: Date.now() + 60_000, mode: "new", submissionKey: "final-key", passport_number: "SECRET",
      fresh: { mode: "family", familyGroupId: "family", active: 0, client_email: "private@example.test", members: [{ sessionId: "member", submissionKey: "member-key", completed: true, documents: ["private-image"] }] } };
    const parsed = parseDraftResume(JSON.stringify(value));
    expect(parsed).toEqual({ version: 1, expiresAt: value.expiresAt, mode: "new", submissionKey: "final-key",
      fresh: { mode: "family", familyGroupId: "family", active: 0, members: [{ sessionId: "member", submissionKey: "member-key", completed: true }] } });
    expect(JSON.stringify(parsed)).not.toMatch(/SECRET|private@example|private-image/);
    for (const change of [{ familyGroupId: "" }, { members: [{ sessionId: "", submissionKey: "member-key", completed: true }] },
      { members: [{ sessionId: "member", submissionKey: "x".repeat(129), completed: true }] }]) {
      expect(parseDraftResume(JSON.stringify({ ...value, fresh: { ...value.fresh, ...change } }))).toBeNull();
    }
  });

  it("keeps completed family members and both operation identities across repeated saves", () => {
    const family = { mode: "family" as const, familyGroupId: "family", active: 1, members: [
      { sessionId: "finished-member", submissionKey: "finished-key", completed: true },
      { sessionId: "active-member", submissionKey: "active-key", completed: false },
    ] };
    const first = saveFreshResume("trip", family, new Date(Date.now() + 60_000).toISOString());
    const second = saveFreshResume("trip", family);
    expect(second.submissionKey).toBe(first.submissionKey);
    expect(readDraftResume("trip")?.fresh).toEqual(family);
    expect(second.expiresAt).toBe(first.expiresAt);
  });
});
