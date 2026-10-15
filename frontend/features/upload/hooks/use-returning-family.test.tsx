import { act, renderHook } from "@testing-library/react";
import { useState, type ComponentProps } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { ReturningFlow } from "@/features/travellers/components/returning-flow";
import { returningApi } from "@/features/travellers/api/returning.api";
import { createFamilyMembers } from "../services/upload-flow-helpers";
import { isFamilyMemberSubmitted } from "../services/family-returning";
import type { FamilyMember } from "../components/upload-flow.types";
import { useReturningFamily } from "./use-returning-family";

vi.mock("@/features/travellers/api/returning.api", () => ({ returningApi: { replacement: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
const saved = { id: "saved-a", extraction_revision: 3, status: "ready_for_client_review" } as PassportSubmission;
function mount() {
  return renderHook(() => {
    const [members, setMembers] = useState<FamilyMember[]>(() => createFamilyMembers(2).map((member, index) => ({ ...member, name: `Person ${index}`, submission: { ...saved, id: `saved-${index}` } })));
    const flow = useReturningFamily({ token: "token", group: { name: "Trip" } as UploadLinkResponse, members, updateMember: (index, update) => setMembers((current) => current.map((member, position) => position === index ? { ...member, ...(typeof update === "function" ? update(member) : update) } : member)) });
    return { ...flow, members, setMembers };
  });
}
function proof(page: ReturnType<typeof useReturningFamily>["verificationPage"]) { return page!.props.children[1].props as ComponentProps<typeof ReturningFlow>; }
const completed = { status: "accepted" as const, participation_id: "participation", source_submission_id: "reused-submission" };

it("binds proof to one owned source and ignores completion from a previously selected family member", () => {
  const { result } = mount();
  act(() => result.current.open(result.current.members[0]));
  const first = proof(result.current.verificationPage);
  expect(first.ownedSource).toEqual({ source_submission_id: "saved-0", expected_extraction_revision: 3, uploadSessionId: result.current.members[0].uploadIdempotencyKey });
  expect(first.initialMethod).toBe("passport");
  act(() => result.current.open(result.current.members[1]));
  act(() => first.onCompleted?.(completed));
  expect(result.current.members.every((member) => !isFamilyMemberSubmitted(member))).toBe(true);
  act(() => proof(result.current.verificationPage).onCompleted?.(completed));
  expect(isFamilyMemberSubmitted(result.current.members[0])).toBe(false);
  expect(isFamilyMemberSubmitted(result.current.members[1])).toBe(true);
  expect(result.current.members[1].submission?.status).toBe("ready_for_client_review");
});

it("invalidates a completed receipt when that member's upload changes and ignores an old pending result", () => {
  const { result } = mount();
  act(() => result.current.open(result.current.members[0]));
  const prior = proof(result.current.verificationPage);
  act(() => prior.onCompleted?.(completed));
  act(() => result.current.setMembers((members) => members.map((member, index) => index === 0 ? { ...member, submission: { ...saved, id: "replacement" } } : member)));
  expect(result.current.verificationPage).toBeNull();
  expect(isFamilyMemberSubmitted(result.current.members[0])).toBe(false);
  act(() => prior.onCompleted?.(completed));
  expect(isFamilyMemberSubmitted(result.current.members[0])).toBe(false);
  expect(result.current.members[1].reuseCompletion).toBeUndefined();
});

it("links an explicit updated document to the verified person before returning to family review", async () => {
  vi.mocked(returningApi.replacement).mockResolvedValue({ status: "candidate_pending_review", match_case_id: "case" });
  const { result } = mount();
  act(() => result.current.open(result.current.members[1]));
  const selected = proof(result.current.verificationPage);
  await act(async () => { selected.onReplace({ reviewVersion: "opaque-review", displayName: "Verified person", changeKind: "scan" }); });
  expect(returningApi.replacement).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ source_submission_id: "saved-1", expected_extraction_revision: 3, review_version: "opaque-review", change_kind: "scan" }), result.current.members[1].uploadIdempotencyKey, expect.any(AbortSignal));
  expect(result.current.members[0].replacementAssociated).toBeUndefined();
  expect(result.current.members[1].replacementAssociated?.sourceSubmissionId).toBe("saved-1");
  expect(isFamilyMemberSubmitted(result.current.members[1])).toBe(false);
});
