import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentDeliveryTracking } from "@/types/document-distribution.types";
import { GroupDocumentDeliveryPanel } from "./group-document-delivery-panel";

const tracking = vi.hoisted(() => ({
  data: undefined as DocumentDeliveryTracking | undefined,
  isLoading: false,
  error: null as Error | null,
}));

vi.mock("@/features/documents/hooks/use-document-distribution", () => ({
  useDocumentDeliveryTracking: () => tracking,
}));

beforeEach(() => {
  tracking.data = undefined;
  tracking.error = null;
  tracking.isLoading = false;
});

describe("compact document delivery summary", () => {
  it("only counts confirmed delivery receipts as delivered", () => {
    tracking.data = {
      group_id: "trip", poll_after_seconds: 5,
      counts: { total: 10, queued: 1, sent: 3, delivered: 2, read: 1, failed: 2, delivery_unknown: 1 },
      deliveries: [{
        delivery_id: "accepted", passenger_id: null, passenger_name: "Sample Traveller",
        passport_number: null, document_type: "visa", document_filename: "visa.pdf",
        phone_number: "+919900001234", status: "submitted", error_message: null,
        status_updated_at: "2026-09-29T00:00:00Z",
      }],
    };
    render(<GroupDocumentDeliveryPanel groupId="trip" />);
    expect(screen.getByText("3 of 10 delivered")).toBeInTheDocument();
    expect(screen.getByText("Awaiting delivery").parentElement).toHaveTextContent("3");
    expect(screen.getByText("Unknown").parentElement).toHaveTextContent("1");
    expect(screen.getByText("Failed").parentElement).toHaveTextContent("2");
    expect(screen.getByText("Accepted by WhatsApp")).toBeInTheDocument();
    expect(screen.getByText("Recent delivery updates").parentElement).not.toHaveAttribute("open");
    expect(screen.getByRole("link", { name: "Manage deliveries" })).toHaveAttribute("href", "/documents/distribution/trip");
  });

  it("keeps an unavailable result distinct from an empty group", () => {
    tracking.error = new Error("Unavailable");
    render(<GroupDocumentDeliveryPanel groupId="trip" />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not be loaded");
    expect(screen.queryByText("No document broadcasts sent yet")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage deliveries" })).toBeInTheDocument();
  });

  it("keeps the empty state compact with a route to prepare documents", () => {
    render(<GroupDocumentDeliveryPanel groupId="trip" />);
    expect(screen.getByText("No document broadcasts sent yet")).toBeInTheDocument();
    expect(screen.queryByText("Recent delivery updates")).not.toBeInTheDocument();
  });
});
