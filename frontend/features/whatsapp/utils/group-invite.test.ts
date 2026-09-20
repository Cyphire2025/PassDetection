import { describe, expect, it } from "vitest";
import { validWhatsAppGroupInviteLink } from "./group-invite";
import { formatMessageType, isWhatsAppMessageType } from "./message-types";
import { parseTrackedWhatsAppActivities } from "./activity-tracking";

describe("WhatsApp group invite URLs", () => {
  it.each(["https://chat.whatsapp.com/ABC123", "https://chat.whatsapp.com/ABC123/", "https://chat.whatsapp.com/ABC123?mode=ac_t", " https://chat.whatsapp.com/ABC123 "])("accepts official invite %s", (link) => expect(validWhatsAppGroupInviteLink(link)).toBe(true));
  it.each(["", "http://chat.whatsapp.com/ABC123", "https://chat.whatsapp.com/", "https://chat.whatsapp.com.evil.test/ABC123", "https://user@chat.whatsapp.com/ABC123", "https://chat.whatsapp.com:443/ABC123", "https://chat.whatsapp.com/ABC123/more", "https://chat.whatsapp.com/ABC123#fragment", "https://chat.whatsapp.com/ABC\t123", "https://chat.whatsapp.com/ABC123?value=a b", "https://chat.whatsapp.com/ABC123?value=\u0000"])("rejects malformed or unofficial invite %s", (link) => expect(validWhatsAppGroupInviteLink(link)).toBe(false));
  it("recognizes group invites in recipient actions and restores activity type", () => {
    expect(formatMessageType("group_invite")).toBe("Group invite");
    expect(isWhatsAppMessageType("group_invite")).toBe(true);
    const records = parseTrackedWhatsAppActivities(JSON.stringify([{ id: "batch", kind: "broadcast", startedAt: 123, title: "Group invite broadcast", contextLabel: "Delegates", sourceGroupId: "group", messageType: "group_invite" }]));
    expect(records[0]?.messageType).toBe("group_invite");
  });
});
