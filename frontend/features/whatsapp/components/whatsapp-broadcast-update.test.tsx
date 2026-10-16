import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { whatsappApi, type WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { groupUpdatesApi } from "../api/group-updates.api";
import { WhatsAppPage } from "./whatsapp-workspace";

vi.mock("./whatsapp-activity-tracker", () => ({ useWhatsAppActivityTracker: () => ({ activities: [], registerActivity: vi.fn() }), WhatsAppActivityInline: () => null }));
vi.mock("../api/whatsapp.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/whatsapp.api")>();
  return { ...actual, whatsappApi: { ...actual.whatsappApi, groups: vi.fn(), group: vi.fn() } };
});
vi.mock("../api/group-updates.api", () => ({ groupUpdatesApi: { preview: vi.fn(), send: vi.fn() } }));
let detail: WhatsAppBroadcastGroupDetail;

beforeEach(() => {
  vi.clearAllMocks();
  detail = {
    id: "broadcast", name: "Bluechip October", is_archived: false, recipient_count: 88, total_contact_count: 88,
    recipient_opt_in_confirmed: true, created_at: "2026-10-16T01:00:00Z", updated_at: "2026-10-16T01:00:00Z",
    recipients: [], support_contacts: [], rejected_contact_count: 0,
    linked_client_groups: [{ id: "trip", name: "Bluechip trip", status: "active" }],
  };
  vi.mocked(whatsappApi.groups).mockImplementation(async (archived = false) => archived === detail.is_archived ? [detail] : []);
  vi.mocked(whatsappApi.group).mockImplementation(async () => detail);
  vi.mocked(groupUpdatesApi.preview).mockImplementation(async (groupId, audience) => ({
    group_id: groupId, audience, preview_token: "a".repeat(64), template_name: "pending_v1", template_language: "en", can_send: true, configuration_error: null, recipients: [],
  }));
});
afterEach(cleanup);

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><WhatsAppPage /></QueryClientProvider>);
}

it.each([0, 1])("opens Send update from the broadcast menu on surface %s without sending", async (surface) => {
  mount();
  fireEvent.click((await screen.findAllByRole("button", { name: "Open actions for Bluechip October" }))[surface]);
  fireEvent.click(screen.getByRole("button", { name: "Send update" }));
  await screen.findByRole("group", { name: "Document submission" });
  expect(screen.getByRole("dialog", { name: "Preview Update Message" })).toBeInTheDocument();
  await waitFor(() => expect(groupUpdatesApi.preview).toHaveBeenCalledWith("trip", expect.any(Object), expect.any(AbortSignal)));
  expect(whatsappApi.group).toHaveBeenCalledWith("broadcast", expect.any(AbortSignal));
  expect(groupUpdatesApi.send).not.toHaveBeenCalled();
});

it("requires a choice when multiple groups are linked instead of using the wrong trip", async () => {
  detail.linked_client_groups!.push({ id: "other", name: "Other trip", status: "active" });
  mount();
  fireEvent.click((await screen.findAllByRole("button", { name: "Open actions for Bluechip October" }))[0]);
  fireEvent.click(screen.getByRole("button", { name: "Send update" }));
  const select = await screen.findByLabelText("Group for update filters");
  expect(groupUpdatesApi.preview).not.toHaveBeenCalled();
  fireEvent.change(select, { target: { value: "other" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue to preview" }));
  await waitFor(() => expect(groupUpdatesApi.preview).toHaveBeenCalledWith("other", expect.any(Object), expect.any(AbortSignal)));
  expect(groupUpdatesApi.send).not.toHaveBeenCalled();
});

it("explains an unlinked broadcast and does not guess a group", async () => {
  detail.linked_client_groups = [];
  mount();
  fireEvent.click((await screen.findAllByRole("button", { name: "Open actions for Bluechip October" }))[0]);
  fireEvent.click(screen.getByRole("button", { name: "Send update" }));
  await screen.findByText(/Link this broadcast to a group in All Groups first/);
  expect(groupUpdatesApi.preview).not.toHaveBeenCalled();
  expect(groupUpdatesApi.send).not.toHaveBeenCalled();
});

it("does not offer update sending on an archived broadcast", async () => {
  detail.is_archived = true;
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Archived broadcasts" }));
  fireEvent.click((await screen.findAllByRole("button", { name: "Open actions for Bluechip October" }))[0]);
  expect(screen.queryByRole("button", { name: "Send update" })).not.toBeInTheDocument();
});
