import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { returningDraftApi } from "./returning-draft.api";
import { freshDraftApi } from "@/features/upload/api/fresh-draft.api";

const post = vi.hoisted(() => vi.fn().mockResolvedValue({ data: { revision: 2 } }));
vi.mock("@/lib/api/client", () => ({ default: { post } }));
beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("member-bound temporary image requests", () => {
  it("sends the selected side predecessor in fresh and returning multipart requests", async () => {
    const file = new File(["synthetic"], "image.jpg", { type: "image/jpeg" });
    await freshDraftApi("group", "member").upload("back", file, 8, "operation", undefined, "previous-back");
    await returningDraftApi.upload("front", file, 9, "replacement", "private-draft", undefined, "previous-front");
    expect(post.mock.calls.map((call) => (call[1] as FormData).get("expected_asset_id"))).toEqual(["previous-back", "previous-front"]);
    expect(post.mock.calls[0][2].headers["X-Upload-Session-ID"]).toBe("member");
    expect(post.mock.calls[1][2].headers["X-Returning-Draft-ID"]).toBe("private-draft");
    await freshDraftApi("group", "member").upload("front", file, 10, "new");
    expect((post.mock.calls[2][1] as FormData).get("expected_asset_id")).toBe("");
  });

  it("keeps the exact revision and capability headers on explicit leave", async () => {
    await freshDraftApi("group", "member").discard(5);
    await returningDraftApi.discard(6, "private-draft");
    expect(post.mock.calls[0]).toMatchObject(["/api/v1/public-drafts/group/discard-documents", { expected_revision: 5 }, { headers: { "X-Upload-Session-ID": "member" } }]);
    expect(post.mock.calls[1]).toMatchObject(["/api/v1/returning/draft/discard-documents", { expected_revision: 6 }, { headers: { "X-Returning-Draft-ID": "private-draft" } }]);
  });

  it("uses a small credentialed keepalive request, without image bytes, on abrupt leave", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 })); vi.stubGlobal("fetch", fetch);
    await freshDraftApi("group", "member").discard(7, undefined, true);
    await returningDraftApi.discard(8, "private-draft", undefined, true);
    expect(post).not.toHaveBeenCalled();
    expect(fetch.mock.calls[0]).toEqual(["/api/v1/public-drafts/group/discard-documents", expect.objectContaining({ method: "POST", credentials: "include", keepalive: true, body: '{"expected_revision":7}', headers: { "Content-Type": "application/json", "X-Upload-Session-ID": "member" } })]);
    expect(fetch.mock.calls[1][1].headers["X-Returning-Draft-ID"]).toBe("private-draft");
  });

  it("heartbeats only through the corresponding scoped lifecycle route", async () => {
    await freshDraftApi("group", "member").activity(); await returningDraftApi.activity("private-draft");
    expect(post.mock.calls.map((call) => call[0])).toEqual(["/api/v1/public-drafts/group/activity", "/api/v1/returning/draft/activity"]);
  });
});
