import { describe, expect, it } from "vitest";
import { reconcileDraft } from "./draft-reconcile";
import { queuedPrivatePreview } from "./private-preview-queue";
import type { DraftPayload } from "../api/returning-draft.api";

const empty = (): DraftPayload => ({ passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {} });

describe("private draft concurrency", () => {
  it("combines a current-trip edit with background extraction without losing either", () => {
    const base = empty();
    const local = { ...base, current_details: { staff_code: "0017" } };
    const remote = { ...base, passport_fields: { given_names: "SYNTHETIC", passport_number: "A1234567" } };
    expect(reconcileDraft(base, local, remote)).toEqual({ ...local, passport_fields: remote.passport_fields });
  });
  it("refuses divergent edits to the same field instead of overwriting another tab", () => {
    const base = { ...empty(), passport_fields: { place_of_issue: "Delhi" } };
    expect(() => reconcileDraft(base, { ...base, passport_fields: { place_of_issue: "Mumbai" } }, { ...base, passport_fields: { place_of_issue: "Bengaluru" } })).toThrow("another window");
  });
  it("respects authoritative removals of unchanged answers and allows matching concurrent edits", () => {
    const base = { ...empty(), custom_answers: { old_question: "old" }, current_details: { staff_code: "old" } };
    const local = { ...base, current_details: { staff_code: "new" } };
    expect(reconcileDraft(base, local, { ...empty(), current_details: { staff_code: "new" } })).toEqual({ ...empty(), current_details: { staff_code: "new" } });
  });
  it("limits image transfers to two and cancels queued work without consuming the next slot", async () => {
    let running = 0; let maximum = 0; const release: Array<() => void> = [];
    const load = () => new Promise<number>((resolve) => { running++; maximum = Math.max(maximum, running); release.push(() => { running--; resolve(1); }); });
    const controllers = Array.from({ length: 4 }, () => new AbortController());
    const first = queuedPrivatePreview(load, controllers[0].signal);
    const second = queuedPrivatePreview(load, controllers[1].signal);
    const cancelled = queuedPrivatePreview(load, controllers[2].signal).catch((cause: DOMException) => cause.name);
    const fourth = queuedPrivatePreview(load, controllers[3].signal);
    expect(release).toHaveLength(2); controllers[2].abort();
    expect(await cancelled).toBe("AbortError");
    release[0](); await first; await Promise.resolve();
    expect(release).toHaveLength(3); expect(maximum).toBe(2);
    release[1](); release[2](); await Promise.all([second, fourth]);
    expect(running).toBe(0);
    expect(await queuedPrivatePreview(async () => "next", new AbortController().signal)).toBe("next");
  });
});
