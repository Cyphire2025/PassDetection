import { beforeEach, expect, it, vi } from "vitest";
const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: client }));
import { whatsappApi } from "./whatsapp.api";

beforeEach(() => vi.clearAllMocks());

it("requests active groups by default and archived groups explicitly", async () => {
  client.get.mockResolvedValue({ data: [] });
  await whatsappApi.groups();
  await whatsappApi.groups(true);
  expect(client.get.mock.calls).toEqual([
    ["/api/v1/whatsapp/groups", { params: { archived: false } }],
    ["/api/v1/whatsapp/groups", { params: { archived: true } }],
  ]);
});

it.each(["archive", "restore"] as const)("uses the %s endpoint and returns the updated group", async (action) => {
  const group = { id: "group-a", is_archived: action === "archive" };
  client.post.mockResolvedValue({ data: group });
  expect(await whatsappApi[action === "archive" ? "archiveGroup" : "restoreGroup"]("group-a")).toEqual(group);
  expect(client.post).toHaveBeenCalledWith(`/api/v1/whatsapp/groups/group-a/${action}`);
});
