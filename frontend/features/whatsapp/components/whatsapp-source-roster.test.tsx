import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { WhatsAppBroadcastGroup } from "../api/whatsapp.api";
import type { WhatsAppBroadcastSourceContacts, WhatsAppSourceContact } from "../api/whatsapp-source-groups.api";
import { SourceContactTable } from "./whatsapp-source-contact-table";
import { SourceRosterPanel } from "./whatsapp-source-roster-panel";
import { WhatsAppBroadcastList } from "./whatsapp-broadcast-list";

function contact(id: number): WhatsAppSourceContact {
  return { source_submission_id: `submission-${id}`, name: `Traveller ${String(id).padStart(3, "0")}`, phone_number: `+91999999${String(id).padStart(4, "0")}`, normalized_phone_number: `+91999999${String(id).padStart(4, "0")}`, issue: null, imported_fields: {} };
}

describe("source traveller roster", () => {
  it("retains every traveller, shared phone and invalid phone without merging names", () => {
    const contacts = [contact(1), { ...contact(2), phone_number: contact(1).phone_number, normalized_phone_number: contact(1).normalized_phone_number }, { ...contact(3), phone_number: "12345", normalized_phone_number: null, issue: "invalid_phone" }];
    render(<SourceContactTable contacts={contacts} />);
    expect(screen.getByText("Traveller 001")).toBeInTheDocument();
    expect(screen.getByText("Traveller 002")).toBeInTheDocument();
    expect(screen.getByText("Traveller 003")).toBeInTheDocument();
    expect(screen.getAllByText(contact(1).phone_number)).toHaveLength(2);
    expect(screen.getAllByText("Shared number · one message")).toHaveLength(2);
    expect(screen.getByText("12345")).toBeInTheDocument();
    expect(screen.getByText("WhatsApp number invalid")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Traveller list pagination" })).toHaveTextContent("1–3 of 3");
  });

  it("pages a long source roster and searches all rows rather than only the current page", () => {
    render(<SourceContactTable contacts={Array.from({ length: 377 }, (_, index) => contact(index + 1))} />);
    expect(screen.getByText("Traveller 001")).toBeInTheDocument();
    expect(screen.queryByText("Traveller 026")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Traveller 026")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search travellers" }), { target: { value: "Traveller 377" } });
    expect(screen.getByText("Traveller 377")).toBeInTheDocument();
    expect(screen.queryByText("Traveller 026")).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Traveller list pagination" })).toHaveTextContent("1–1 of 1");
  });

  it("marks import-only sources and keeps traveller counts separate from delivery numbers", () => {
    const data: WhatsAppBroadcastSourceContacts = {
      sources: [{ id: "source-a", name: "Imported trip", import_only: true }],
      total_contacts: 377, unique_phone_count: 366, needs_attention_count: 2, shared_phone_count: 9,
      contacts: [{ ...contact(1), source_group_id: "source-a", source_group_name: "Imported trip", source_import_only: true, recipient_id: "recipient-a" }],
    };
    render(<SourceRosterPanel data={data} isLoading={false} isFetching={false} error={null} onRetry={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Imported trip Import only" })).toHaveAttribute("href", "/passports/groups/source-a");
    expect(screen.getByText("377")).toBeInTheDocument();
    expect(screen.getByText("366")).toBeInTheDocument();
    expect(screen.getByText(/9 additional travellers share/)).toBeInTheDocument();
    expect(screen.getByText(/2 traveller rows need/)).toBeInTheDocument();
  });

  it("provides a refresh action after roster loading fails", () => {
    const retry = vi.fn();
    render(<SourceRosterPanel data={undefined} isLoading={false} isFetching={false} error={new Error("Source temporarily unavailable")} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Source temporarily unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Refresh travellers" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("shows source traveller totals and the import marker on broadcast cards without calling shared numbers exceptions", () => {
    const group: WhatsAppBroadcastGroup = { id: "broadcast-a", name: "Imported travellers", recipient_count: 366, total_contact_count: 366, source_contact_count: 377, has_import_only_source: true, recipient_opt_in_confirmed: true, created_at: "2026-09-21T00:00:00Z", updated_at: "2026-09-21T00:00:00Z" };
    render(<WhatsAppBroadcastList groups={[group]} totalCount={1} isLoading={false} renderActions={() => null} onCreate={vi.fn()} />);
    const row = screen.getByRole("row", { name: /Imported travellers/ });
    expect(within(row).getByText("Import only")).toBeInTheDocument();
    expect(within(row).getByText("377 travellers")).toBeInTheDocument();
    expect(within(row).getByText("366 delivery numbers")).toBeInTheDocument();
    expect(screen.queryByText(/contact exceptions/)).not.toBeInTheDocument();
  });
});
