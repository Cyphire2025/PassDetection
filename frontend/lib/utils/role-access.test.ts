import { describe, expect, it } from "vitest";
import { canAccessWhatsAppBroadcasts, canDeletePassportSubmissions } from "./role-access";

describe("office workflow role access", () => {
  it.each([
    ["super_admin", true, true],
    ["agency_admin", true, true],
    ["agency_manager", true, true],
    ["agency_staff", true, false],
    ["agency_coordinator", false, false],
    [null, false, false],
    [undefined, false, false],
  ] as const)("%s has WhatsApp access=%s and submission deletion=%s", (role, whatsapp, deletion) => {
    expect(canAccessWhatsAppBroadcasts(role)).toBe(whatsapp);
    expect(canDeletePassportSubmissions(role)).toBe(deletion);
  });
});
