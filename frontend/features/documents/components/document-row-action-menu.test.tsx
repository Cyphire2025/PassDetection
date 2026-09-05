// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DistributedDocument } from "@/types/document-distribution.types";
import { DocumentRowActionMenu } from "./document-workspace-review";

const document: DistributedDocument = {
  id: "document-1", original_filename: "passenger-visa.pdf", document_type: "visa", detected_type: "visa",
  match_status: "matched", match_confidence: 1, match_reason: null, extracted_name: null,
  extracted_passport_number: null, extracted_reference: null, source: "manual", delivery_status: "not_sent",
  sent_to: null, last_sent_at: null, can_resend: false, url: null,
};

function setup() {
  const remove = vi.fn();
  const result = render(<div data-testid="scrolling-table" style={{ overflow: "auto", width: 320 }}>
    <DocumentRowActionMenu row={{ passenger_id: "passenger-1", passenger_name: "Alex", passport_number: null,
      departure_city: null, document, documents: [document] }} documents={[document]} documentType="visa"
      pending={false} onReupload={vi.fn()} onRemoveAssignment={remove} />
  </div>);
  const trigger = screen.getByRole("button", { name: "Alex document actions" });
  fireEvent.click(trigger);
  return { ...result, trigger, remove };
}

describe("document actions inside a scrolling table", () => {
  it("renders outside the overflow boundary and supports keyboard dismissal", () => {
    const { trigger, container, remove } = setup();
    const menu = screen.getByRole("menu", { name: "Alex document actions" });
    expect(container.contains(menu)).toBe(false);
    expect(screen.getByRole("menuitem", { name: "Add another document" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: /Remove assignment/ })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(remove).not.toHaveBeenCalled();
  });

  it("closes when the table moves or viewport changes, and preserves explicit actions", () => {
    const { trigger, remove } = setup();
    fireEvent.scroll(screen.getByTestId("scrolling-table"));
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(trigger);
    fireEvent.resize(window);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: /Remove assignment/ }));
    expect(remove).toHaveBeenCalledWith("document-1");
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
