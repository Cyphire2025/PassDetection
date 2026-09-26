import { describe, expect, it } from "vitest";
import { createFamilyMembers } from "./upload-flow-helpers";
import { familyUploadReducer } from "./family-upload-state";
import { uploadOperationReducer } from "./upload-operation-state";

describe("family upload transitions", () => {
  it("resizes while preserving saved member identity, credential, contact, and corrected fields", () => {
    const members = createFamilyMembers(3);
    members[0] = { ...members[0], email: "head@example.com", reviewFields: { surname: "Corrected" } };
    const initial = { members, activeIndex: 2, countInput: "3" };
    const smaller = familyUploadReducer(initial, { type: "count-edited", input: "2", candidates: [] });
    expect(smaller.members[0]).toEqual(members[0]);
    expect(smaller.members[1]).toBe(members[1]);
    expect(smaller.activeIndex).toBe(1);
    const candidates = createFamilyMembers(4);
    const larger = familyUploadReducer(smaller, { type: "count-edited", input: "4", candidates });
    expect(larger.members[0].uploadIdempotencyKey).toBe(members[0].uploadIdempotencyKey);
    expect(larger.members[2]).toBe(candidates[2]);
    expect(larger.members[2].uploadIdempotencyKey).not.toBe(members[2].uploadIdempotencyKey);
  });
  it.each(["", "1", "999"])("keeps members while count input %s is incomplete or outside limits", (input) => {
    const initial = { members: createFamilyMembers(2), activeIndex: 1, countInput: "2" };
    const result = familyUploadReducer(initial, { type: "count-edited", input, candidates: [] });
    expect(result.members).toBe(initial.members);
    expect(result.countInput).toBe(input);
  });
  it("normalizes empty input and ignores invalid selection without losing members", () => {
    const initial = { members: createFamilyMembers(2), activeIndex: 1, countInput: "" };
    const normalized = familyUploadReducer(initial, { type: "count-normalized", candidates: [] });
    expect(normalized.countInput).toBe("2");
    expect(familyUploadReducer(normalized, { type: "selected", index: 9 })).toBe(normalized);
    expect(familyUploadReducer(normalized, { type: "count-edited", input: "-1", candidates: [] })).toBe(normalized);
  });
  it("merges a late extraction patch with the current review edits, not an old snapshot", () => {
    const initial = { members: createFamilyMembers(2), activeIndex: 0, countInput: "2" };
    const corrected = familyUploadReducer(initial, { type: "member-updated", index: 1, update: { reviewFields: { surname: "Manual" } } });
    const completed = familyUploadReducer(corrected, { type: "member-updated", index: 1,
      update: (member) => ({ reviewFields: { ...member.reviewFields, passport_number: "SYNTHETIC" } }),
    });
    expect(completed.members[1].reviewFields).toEqual({ surname: "Manual", passport_number: "SYNTHETIC" });
    expect(completed.members[0]).toBe(initial.members[0]);
  });
  it("makes obsolete operation events inert", () => {
    const current = uploadOperationReducer({ status: "idle", generation: 2 }, { type: "started", generation: 3, kind: "retry" });
    expect(uploadOperationReducer(current, { type: "finished", generation: 2 })).toBe(current);
    expect(uploadOperationReducer(current, { type: "started", generation: 1, kind: "upload" })).toBe(current);
  });
});
