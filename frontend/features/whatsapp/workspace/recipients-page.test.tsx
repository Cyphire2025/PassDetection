import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useBroadcast } from "./broadcast-workspace-shell";
import { useWhatsAppBroadcastSourceContacts } from "../hooks/use-whatsapp-source-groups";
import { BroadcastRecipientsPage } from "./recipients-page";
import { syntheticRecipientGroup, syntheticSourceContact } from "./recipient-workspace.test-fixture";

vi.mock("./broadcast-workspace-shell", () => ({ useBroadcast: vi.fn() }));
vi.mock("../hooks/use-whatsapp-source-groups", () => ({ useWhatsAppBroadcastSourceContacts: vi.fn() }));
vi.mock("../hooks/use-whatsapp", () => ({
  useDeleteWhatsAppRecipient: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useUpdateWhatsAppRecipientPhone: () => ({ isPending: false, reset: vi.fn() }),
  useUpdateWhatsAppRecipientDetails: () => ({ isPending: false, reset: vi.fn() }),
}));

const clients: QueryClient[] = [];
beforeEach(() => {
  vi.mocked(useBroadcast).mockReturnValue(syntheticRecipientGroup(120));
  vi.mocked(useWhatsAppBroadcastSourceContacts).mockReturnValue({
    data: undefined, error: null,
  } as ReturnType<typeof useWhatsAppBroadcastSourceContacts>);
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
});
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}><BroadcastRecipientsPage /></QueryClientProvider>);
}

it("pages all recipients and searches imported fields beyond the visible page", () => {
  mount();
  expect(screen.getByRole("navigation", { name: "Recipients pagination" })).toHaveTextContent("1–50 of 120");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByText("Traveller 050")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Search recipients" }), { target: { value: "Team 119" } });
  expect(screen.getByText("Traveller 119")).toBeInTheDocument();
  expect(screen.queryByText("Traveller 050")).not.toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "Recipients pagination" })).toHaveTextContent("1–1 of 1");
});

it("keeps shared source travellers distinct and replaces the merged fallback only when source people exist", () => {
  const group = syntheticRecipientGroup(2);
  group.source_contact_count = 2;
  group.recipients[0].merged_contacts = [{ id: "merged", name: "Merged fallback", imported_fields: {} }];
  vi.mocked(useBroadcast).mockReturnValue(group);
  vi.mocked(useWhatsAppBroadcastSourceContacts).mockReturnValue({
    data: { contacts: [syntheticSourceContact("Source traveller A", "recipient-0"), syntheticSourceContact("Source traveller B", "recipient-0")] },
    error: null,
  } as ReturnType<typeof useWhatsAppBroadcastSourceContacts>);
  mount();
  expect(screen.getByRole("button", { name: "All recipients (3)" })).toBeInTheDocument();
  expect(screen.getByText("Source traveller A")).toBeInTheDocument();
  expect(screen.getByText("Source traveller B")).toBeInTheDocument();
  expect(screen.queryByText("Merged fallback")).not.toBeInTheDocument();
  expect(screen.getByText("Traveller 001")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Actions for Source traveller A" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "View details" }));
  const detail = screen.getByRole("region", { name: "Detail fields for Source traveller A" });
  expect(within(detail).getByText("These details are maintained in the linked source group.")).toBeInTheDocument();
  expect(within(detail).queryByRole("button", { name: "Edit details" })).not.toBeInTheDocument();
});

it("uses the latest resend result for counts and filters while retaining import-order sorting", () => {
  const group = syntheticRecipientGroup(3);
  group.recipients[0].name = "Zebra";
  group.recipients[0].message_statuses = [{
    message_type: "welcome", status: "sent", latest_resend_status: "failed", already_sent: true,
    resend_blocked: false, submitted_at: null, status_updated_at: "2026-01-01T00:00:00Z",
  }];
  vi.mocked(useBroadcast).mockReturnValue(group);
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Welcome failed (2)" }));
  expect(screen.getByText("Zebra")).toBeInTheDocument();
  expect(screen.getByText("Traveller 001")).toBeInTheDocument();
  expect(screen.queryByText("Traveller 002")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Sort recipients" }), { target: { value: "import" } });
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("Zebra");
});

it("keeps archived broadcasts read-only while allowing recipient details", () => {
  vi.mocked(useBroadcast).mockReturnValue({ ...syntheticRecipientGroup(2), is_archived: true });
  mount();
  expect(screen.getByRole("button", { name: "Add recipients" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Actions for Traveller 000" }));
  expect(screen.getByRole("menuitem", { name: "View details" })).toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "Remove recipient" })).not.toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "Edit WhatsApp number" })).not.toBeInTheDocument();
});

it("does not rescan unchanged welcome histories while typing in a 512-recipient roster", () => {
  const group = syntheticRecipientGroup(512);
  let historyReads = 0;
  for (const recipient of group.recipients) {
    Object.defineProperty(recipient, "message_statuses", { enumerable: true, get() { historyReads += 1; return []; } });
  }
  vi.mocked(useBroadcast).mockReturnValue(group);
  mount();
  historyReads = 0;
  fireEvent.change(screen.getByRole("searchbox", { name: "Search recipients" }), { target: { value: "Team 511" } });
  expect(screen.getByText("Traveller 511")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Welcome failed (256)" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Welcome not sent (256)" })).toBeInTheDocument();
  expect(historyReads).toBeLessThanOrEqual(100);
});
