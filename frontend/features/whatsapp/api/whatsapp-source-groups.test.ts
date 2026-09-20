import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { get, post } }));
import { whatsappSourceGroupsApi } from "./whatsapp-source-groups.api";

beforeEach(() => { vi.clearAllMocks(); });

describe("create broadcast from source group API", () => {
  it("requests scoped source groups and propagates cancellation", async () => {
    const groups = [{ id: "source-a", name: "September trip", submission_count: 4 }];
    get.mockResolvedValue({ data: groups });
    const controller = new AbortController();
    expect(await whatsappSourceGroupsApi.list(controller.signal)).toEqual(groups);
    expect(get).toHaveBeenCalledWith("/api/v1/whatsapp/source-groups", { signal: controller.signal });
  });

  it("requests a preview for the selected group with its own cancellation signal", async () => {
    const preview = { source_group_id: "source-b", preview_revision: "revision-b" };
    get.mockResolvedValue({ data: preview });
    const controller = new AbortController();
    expect(await whatsappSourceGroupsApi.preview("source-b", controller.signal)).toEqual(preview);
    expect(get).toHaveBeenCalledWith("/api/v1/whatsapp/source-groups/source-b/preview", { signal: controller.signal });
  });

  it("creates from the reviewed server source rather than posting editable copied contacts", async () => {
    const group = { id: "broadcast-a", name: "Custom trip name" };
    post.mockResolvedValue({ data: { group, source: {} } });
    const supportContacts = [{ name: "Travel support", phone_number: "+919999999999" }];
    expect(await whatsappSourceGroupsApi.create({
      sourceGroupId: "source-a", name: "Custom trip name", supportContacts,
      recipientOptInConfirmed: true, previewRevision: "reviewed-revision",
    })).toEqual(group);
    expect(post).toHaveBeenCalledExactlyOnceWith("/api/v1/whatsapp/groups/from-client-group", {
      source_group_id: "source-a", name: "Custom trip name", support_contacts: supportContacts,
      recipient_opt_in_confirmed: true, preview_revision: "reviewed-revision",
    });
  });
});
