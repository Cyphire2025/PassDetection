import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WhatsAppSourceContact } from "../api/whatsapp-source-groups.api";
import { SourceContactTable } from "./whatsapp-source-contact-table";

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

});
