import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { groupUpdatesApi, type GroupUpdateRecipient } from "../api/group-updates.api";
import { whatsappApi, type WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { whatsappSourceGroupsApi } from "../api/whatsapp-source-groups.api";
import { RecipientListDialog } from "./whatsapp-recipient-dialog";

vi.mock("./whatsapp-activity-tracker", () => ({ useWhatsAppActivityTracker: () => ({ activities: [], registerActivity: vi.fn() }), WhatsAppActivityInline: () => null }));
vi.mock("../api/group-updates.api", () => ({ groupUpdatesApi: { preview: vi.fn(), send: vi.fn() } }));
vi.mock("../api/whatsapp.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/whatsapp.api")>();
  return { ...actual, whatsappApi: { ...actual.whatsappApi, group: vi.fn(), recipientRoster: vi.fn() } };
});
const group: WhatsAppBroadcastGroupDetail = {
  id: "broadcast", name: "October trip", recipient_count: 6, total_contact_count: 6,
  recipient_opt_in_confirmed: true, created_at: "2026-10-16T00:00:00Z", updated_at: "2026-10-16T00:00:00Z",
  recipients: [], support_contacts: [], rejected_contact_count: 0,
  linked_client_groups: [{ id: "trip", name: "Linked trip", status: "active" }],
};
let rows: GroupUpdateRecipient[];
beforeEach(() => {
  vi.clearAllMocks();
  rows = ["read", "failed", null, "delivery_unknown", "queued", "submitted"].map((status, i) => ({
    audience_key: `person:${i}`, name: `Traveller ${i}`, phone_number: `+91999999999${i}`, phone_source: "submitted", submission_status: "submitted",
    recipient_id: `recipient:${i}`, broadcast_group_id: "broadcast", passenger_id: `person:${i}`, document_count: 1, confirmed_count: 0,
    eligible: status !== "delivery_unknown" && status !== "queued", reason: null, passport_number: `P123456${i}`,
    latest_update_status: status, latest_update_at: status ? "2026-10-16T06:00:00Z" : null, update_attempt_count: status ? 1 : 0,
    latest_update: status ? { id: `attempt:${i}`, status, phone_number: i === 1 ? "+918888888888" : `+91999999999${i}`, created_at: "2026-10-16T05:00:00Z", status_updated_at: "2026-10-16T06:00:00Z", message: "Dear Delegates\nYour visa is being processed.", error: status === "failed" ? "131049: Provider declined delivery" : null, template_name: "pending_v1", provider_message_id: "wamid.saved", document_type: "visa" } : null,
  }));
  vi.mocked(whatsappApi.group).mockResolvedValue(group);
  vi.mocked(whatsappApi.recipientRoster).mockResolvedValue({ items: [], counts: { all: 0, sent: 0, failed: 0, rejected: 0, replaced: 0, unidentified: 0 } });
  vi.spyOn(whatsappSourceGroupsApi, "groupContacts").mockResolvedValue({ sources: [], contacts: [], total_contacts: 0, unique_phone_count: 0, shared_phone_count: 0, needs_attention_count: 0 });
  vi.mocked(groupUpdatesApi.preview).mockImplementation(async (groupId, audience) => ({ group_id: groupId, audience, recipients: rows, can_send: true, preview_token: "a".repeat(64), template_name: "pending_v1", template_language: "en", configuration_error: null }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function openUpdates() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><RecipientListDialog group={group} onClose={vi.fn()} /></QueryClientProvider>);
  fireEvent.change(await screen.findByLabelText("Message type"), { target: { value: "document_update" } });
  await screen.findByRole("region", { name: "Update message delivery" });
}

it("offers Update message in the real recipient dropdown and shows current results from legacy updates", async () => {
  await openUpdates();
  expect(screen.getByRole("option", { name: "Update message" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sent 2" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Failed 1" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Not Sent 1" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Need Review 1" })).toBeInTheDocument();
  const region = screen.getByRole("region", { name: "Update message delivery" });
  expect(within(region).getByText("Read", { selector: "span" })).toBeInTheDocument();
  expect(within(region).getByText("Queued", { selector: "span" })).toBeInTheDocument();
  expect(within(region).getByText("Submitted to WhatsApp", { selector: "span" })).toBeInTheDocument();
  expect(groupUpdatesApi.send).not.toHaveBeenCalled();
});

it("filters failures and expands the saved content, actual number, error, timestamps and identifying details", async () => {
  await openUpdates();
  fireEvent.click(screen.getByRole("button", { name: "Failed 1" }));
  const region = screen.getByRole("region", { name: "Update message delivery" });
  expect(within(region).getByText("Traveller 1")).toBeInTheDocument();
  expect(within(region).queryByText("Traveller 0")).not.toBeInTheDocument();
  fireEvent.click(within(region).getByText("View recipient & update details"));
  expect(await within(region).findByText("Dear Delegates Your visa is being processed.")).toBeInTheDocument();
  expect(within(region).getByText("+918888888888")).toBeInTheDocument();
  expect(within(region).getByText("P1234561")).toBeInTheDocument();
  expect(within(region).getByText("pending_v1")).toBeInTheDocument();
  expect(within(region).getByText("Requested")).toBeInTheDocument();
  expect(within(region).getByText("Last status update")).toBeInTheDocument();
  expect(within(region).getByText("wamid.saved")).toBeInTheDocument();
  expect(within(region).getAllByText(/131049: Provider declined delivery/).length).toBeGreaterThan(0);
  expect(groupUpdatesApi.send).not.toHaveBeenCalled();
});

it("supports exact result filtering and excludes other broadcasts", async () => {
  rows.push({ ...rows[0], audience_key: "other", name: "Other broadcast person", broadcast_group_id: "other" });
  await openUpdates();
  expect(screen.queryByText("Other broadcast person")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: /Latest result/ }), { target: { value: "queued" } });
  const region = screen.getByRole("region", { name: "Update message delivery" });
  expect(within(region).getByText("Traveller 4")).toBeInTheDocument();
  expect(within(region).queryByText("Traveller 0")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Message type"), { target: { value: "welcome" } });
  expect(screen.queryByRole("region", { name: "Update message delivery" })).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Welcome message" })).toBeInTheDocument();
});
