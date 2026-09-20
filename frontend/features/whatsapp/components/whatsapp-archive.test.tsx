import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { whatsappApi } from "../api/whatsapp.api";
import { whatsappSourceGroupsApi } from "../api/whatsapp-source-groups.api";
import { WHATSAPP_QUERY_KEYS } from "../hooks/use-whatsapp";
import { WhatsAppPage } from "./whatsapp-workspace";
import { RecipientListDialog } from "./whatsapp-recipient-dialog";

vi.mock("./whatsapp-activity-tracker", () => ({
  useWhatsAppActivityTracker: () => ({ activities: [], registerActivity: vi.fn() }),
  WhatsAppActivityInline: () => null,
}));
vi.mock("../api/whatsapp.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/whatsapp.api")>();
  return { ...actual, whatsappApi: {
    ...actual.whatsappApi, groups: vi.fn(), group: vi.fn(), archiveGroup: vi.fn(),
    restoreGroup: vi.fn(), deleteGroup: vi.fn(), recipientRoster: vi.fn(),
  } };
});

function broadcast(id: string, name: string, archived = false): WhatsAppBroadcastGroupDetail {
  return {
    id, name, is_archived: archived, archived_at: archived ? "2026-09-19T09:00:00Z" : null,
    recipient_count: 1, total_contact_count: 1, recipient_opt_in_confirmed: true,
    created_at: "2026-09-18T09:00:00Z", updated_at: "2026-09-19T09:00:00Z",
    recipients: [{ id: `${id}-recipient`, name: "Passenger A", phone_number: "+919999999999", normalized_phone_number: "+919999999999", imported_fields: {}, message_statuses: [] }],
    support_contacts: [{ id: "support-a", name: "Trip support", phone_number: "+919999999998", normalized_phone_number: "+919999999998" }],
    rejected_contact_count: 0,
  };
}

let records: WhatsAppBroadcastGroupDetail[];

beforeEach(() => {
  vi.clearAllMocks();
  records = [broadcast("live", "September travellers"), broadcast("old", "August travellers", true)];
  vi.mocked(whatsappApi.groups).mockImplementation(async (archived = false) => records.filter((group) => group.is_archived === archived));
  vi.mocked(whatsappApi.group).mockImplementation(async (id) => records.find((group) => group.id === id)!);
  vi.mocked(whatsappApi.recipientRoster).mockImplementation(async (id) => ({
    items: records.find((group) => group.id === id)!.recipients.map((recipient, display_order) => ({ kind: "recipient" as const, recipient, display_order })),
    counts: { all: 1, sent: 0, failed: 0, rejected: 0, replaced: 0, unidentified: 0 },
  }));
  for (const [method, archived] of [["archiveGroup", true], ["restoreGroup", false]] as const) {
    vi.mocked(whatsappApi[method]).mockImplementation(async (id) => {
      const updated = { ...records.find((group) => group.id === id)!, is_archived: archived, archived_at: archived ? "2026-09-19T10:00:00Z" : null };
      records = records.map((group) => group.id === id ? updated : group);
      return updated;
    });
  }
});

function renderWorkspace(group?: WhatsAppBroadcastGroupDetail) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}>{group ? <RecipientListDialog group={group} onClose={vi.fn()} /> : <WhatsAppPage />}</QueryClientProvider>);
  return { ...view, client };
}

async function openActions(name: string) {
  const buttons = await screen.findAllByRole("button", { name: `Open actions for ${name}` });
  fireEvent.click(buttons[0]);
}

describe("WhatsApp archive workspace", () => {
  it("shows every linked traveller separately from the unique delivery list", async () => {
    records[0].linked_client_groups = [{ id: "source-a", name: "Imported trip", status: "active", import_only: true }];
    records[0].source_contact_count = 3;
    const contact = { phone_number: "+919999999999", normalized_phone_number: "+919999999999", issue: null, imported_fields: {}, source_group_id: "source-a", source_group_name: "Imported trip", source_import_only: true, recipient_id: "live-recipient" };
    const roster = vi.spyOn(whatsappSourceGroupsApi, "groupContacts").mockResolvedValue({
      sources: [{ id: "source-a", name: "Imported trip", import_only: true }], total_contacts: 3, unique_phone_count: 1, shared_phone_count: 1, needs_attention_count: 1,
      contacts: [
        { ...contact, source_submission_id: "person-a", name: "Traveller A" },
        { ...contact, source_submission_id: "person-b", name: "Traveller B" },
        { ...contact, source_submission_id: "person-c", name: "Traveller C", phone_number: "invalid", normalized_phone_number: null, issue: "invalid_phone", recipient_id: null },
      ],
    });
    renderWorkspace(records[0]);
    expect(await screen.findByRole("button", { name: /Travellers/ })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText("Traveller A")).toBeInTheDocument();
    expect(screen.getByText("Traveller B")).toBeInTheDocument();
    expect(screen.getByText("Traveller C")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Delivery numbers/ })).toHaveTextContent("1");
    fireEvent.click(screen.getByRole("button", { name: /Delivery numbers/ }));
    expect(screen.queryByText("Traveller B")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Delivery numbers/ })).toHaveAttribute("aria-current", "page");
    roster.mockRestore();
  });
  it("starts collapsed and retains the chosen expansion while searching", async () => {
    renderWorkspace();
    await screen.findAllByText("September travellers");
    const toggle = screen.getByRole("button", { name: "Archived broadcasts" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent("1");
    expect(screen.queryByText("August travellers")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("August travellers")).toHaveLength(2);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search WhatsApp broadcast groups" }), { target: { value: "August" } });
    await screen.findByText("No active broadcasts match this search");
    expect(screen.getByRole("button", { name: "Archived broadcasts" })).toHaveAttribute("aria-expanded", "true");
    await openActions("August travellers");
    fireEvent.click(screen.getByRole("button", { name: "Archived broadcasts" }));
    expect(screen.queryByText("August travellers")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore Broadcast" })).not.toBeInTheDocument();
  });

  it("loads active and archived lists separately and searches both", async () => {
    renderWorkspace();
    await openActions("September travellers");
    expect(whatsappApi.groups).toHaveBeenCalledWith(false);
    expect(whatsappApi.groups).toHaveBeenCalledWith(true);
    expect(screen.getByRole("button", { name: "Archive Broadcast" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Delete Broadcast" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Archived broadcasts" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search WhatsApp broadcast groups" }), { target: { value: "August" } });
    expect(await screen.findByText("No active broadcasts match this search")).toBeInTheDocument();
    expect(screen.getAllByText("August travellers")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Archive Broadcast" })).not.toBeInTheDocument();
  });

  it("confirms archive, retains the roster and refreshes both lists and detail", async () => {
    const { client } = renderWorkspace();
    client.setQueryData(WHATSAPP_QUERY_KEYS.group("live"), records[0]);
    await openActions("September travellers");
    fireEvent.click(screen.getByRole("button", { name: "Archive Broadcast" }));
    const dialog = screen.getByRole("dialog", { name: "Archive WhatsApp broadcast?" });
    expect(dialog).toHaveTextContent("delivery history will be retained");
    expect(whatsappApi.archiveGroup).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Archive Broadcast" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(whatsappApi.archiveGroup).toHaveBeenCalledWith("live", expect.anything());
    expect(client.getQueryData<WhatsAppBroadcastGroupDetail>(WHATSAPP_QUERY_KEYS.group("live"))?.is_archived).toBe(true);
    expect(records.find((group) => group.id === "live")?.recipients).toHaveLength(1);
    expect(screen.getByText("No active broadcasts")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Archived broadcasts" }));
    await openActions("September travellers");
    expect(screen.getByRole("button", { name: "Restore Broadcast" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Send Welcome Message" })).not.toBeInTheDocument();
  });

  it("restores an archived broadcast to the active list", async () => {
    renderWorkspace();
    await screen.findAllByText("September travellers");
    fireEvent.click(screen.getByRole("button", { name: "Archived broadcasts" }));
    await openActions("August travellers");
    expect(screen.queryByRole("button", { name: "Send Reminder" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restore Broadcast" }));
    await screen.findByText("No archived broadcasts");
    await openActions("August travellers");
    expect(screen.getByRole("button", { name: "Send Reminder" })).toBeEnabled();
    expect(whatsappApi.deleteGroup).not.toHaveBeenCalled();
  });

  it("keeps active data when queued delivery prevents archiving", async () => {
    vi.mocked(whatsappApi.archiveGroup).mockRejectedValue({ response: { data: { detail: "Wait for queued deliveries to finish." } } });
    renderWorkspace();
    await openActions("September travellers");
    fireEvent.click(screen.getByRole("button", { name: "Archive Broadcast" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Archive Broadcast" }));
    expect(await screen.findByText("Wait for queued deliveries to finish.")).toBeInTheDocument();
    expect(records[0].is_archived).toBe(false);
    expect(screen.getAllByText("September travellers")).toHaveLength(2);
  });

  it("pages long lists and resets the page when searching", async () => {
    records = Array.from({ length: 21 }, (_, index) => broadcast(`group-${index}`, `Trip ${String(index + 1).padStart(2, "0")}`));
    renderWorkspace();
    const navigation = await screen.findByRole("navigation", { name: "Active broadcasts pagination" });
    expect(screen.queryByText("Trip 21")).not.toBeInTheDocument();
    fireEvent.click(within(navigation).getByRole("button", { name: "Next" }));
    expect(screen.getAllByText("Trip 21")).toHaveLength(2);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search WhatsApp broadcast groups" }), { target: { value: "Trip 01" } });
    expect(await screen.findAllByText("Trip 01")).toHaveLength(2);
    expect(screen.queryByRole("navigation", { name: "Active broadcasts pagination" })).not.toBeInTheDocument();
  });

  it("allows archived recipient history and search while disabling every editor", async () => {
    renderWorkspace(records[1]);
    await screen.findByText("Passenger A");
    expect(screen.getByText(/This broadcast is archived and read-only/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add recipients" })).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search current recipients" })).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: "Select Passenger A" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit WhatsApp number", hidden: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove Passenger A from broadcast", hidden: true })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Resend welcome" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Broadcast details" }));
    expect(screen.getByRole("textbox", { name: "Group name" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save Details" })).toBeDisabled();
  });

  it("does not let an older active detail response unlock a freshly archived row", async () => {
    vi.mocked(whatsappApi.group).mockResolvedValue({ ...records[1], is_archived: false, archived_at: null });
    renderWorkspace(records[1]);
    await screen.findByText("Passenger A");
    expect(screen.getByRole("checkbox", { name: "Select Passenger A" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Add recipients" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Broadcast details" }));
    expect(screen.getByRole("textbox", { name: "Group name" })).toBeDisabled();
  });
});
