import { beforeEach, describe, expect, it } from "vitest";
import { actorId, agencyId, batch, draft } from "./notification-test-fixtures";
import { clearPendingSend, pendingSendKey, persistPendingSend, readPendingSend } from "./pending-send";

beforeEach(() => sessionStorage.clear());

describe("Notification recovery marker", () => {
  it("stores only request/draft IDs and isolates different agencies and actors", () => {
    const key = pendingSendKey(agencyId, actorId);
    const marker = { request_id: batch.request_id, draft_id: draft.id };
    persistPendingSend(key, marker);
    expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual(marker);
    expect(readPendingSend(key)).toEqual(marker);
    expect(readPendingSend(pendingSendKey("other-agency", actorId))).toBeNull();
    expect(readPendingSend(pendingSendKey(agencyId, "other-actor"))).toBeNull();
    expect(sessionStorage.getItem(key)).not.toContain(draft.title);
    expect(sessionStorage.getItem(key)).not.toContain(draft.body);
    clearPendingSend(key);
    expect(readPendingSend(key)).toBeNull();
  });

  it("does not use malformed stored identifiers in API requests", () => {
    const key = pendingSendKey(agencyId, actorId);
    sessionStorage.setItem(key, JSON.stringify({ request_id: "../../outside", draft_id: draft.id }));
    expect(readPendingSend(key)).toBeNull();
    sessionStorage.setItem(key, "not json");
    expect(readPendingSend(key)).toBeNull();
  });
});
