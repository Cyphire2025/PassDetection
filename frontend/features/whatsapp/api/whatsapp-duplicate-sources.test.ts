import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { whatsappApi } from "./whatsapp.api";

vi.mock("@/lib/api/client", () => ({ default: { post: vi.fn() } }));
beforeEach(() => { vi.clearAllMocks(); vi.mocked(apiClient.post).mockResolvedValue({ data: {} }); });
describe("source-only workbook transport", () => {
  it.each(["create", "add"] as const)("preserves edited recipients and repeated source files when saving %s", async (operation) => {
    const first = new File(["one"], "one.xlsx"); const second = new File(["two"], "two.xlsx");
    const contacts = [{ name: "Edited recipient", phone_number: "+918888888888" }];
    const input = { contacts, rejectedContacts: [], recipientOptInConfirmed: true, duplicateSourceFiles: [first, second] };
    if (operation === "create") await whatsappApi.createGroup({ ...input, name: "Test broadcast", supportContacts: [{ name: "Support", phone_number: "+917777777777" }] });
    else await whatsappApi.addRecipients({ ...input, groupId: "group" });
    const body = vi.mocked(apiClient.post).mock.calls[0][1] as FormData;
    expect(JSON.parse(body.get("contacts_json") as string)).toEqual(contacts);
    expect(body.getAll("duplicate_source_files")).toEqual([first, second]);
    expect(body.has("contacts_file")).toBe(false);
  });
});
