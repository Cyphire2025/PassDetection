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
});
