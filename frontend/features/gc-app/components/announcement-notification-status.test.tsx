import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAnnouncementNotificationStatus } from "../api/announcement-notification-status.api";
import { AnnouncementNotificationStatusPanel } from "./announcement-notification-status";

vi.mock("../api/announcement-notification-status.api", () => ({
  getAnnouncementNotificationStatus: vi.fn(),
}));

const loadStatus = vi.mocked(getAnnouncementNotificationStatus);
const status = {
  announcement_id: "announcement-1", provider_enabled: false,
  recipient_counts: { total: 4, queued: 2, sent: 1, failed: 1, cancelled: 0, read: 2, no_active_registration: 1 },
  device_delivery_counts: { total: 6, submitting: 1, retry: 1, receipt_pending: 2, delivered: 1, failed: 1, cancelled: 0 },
  failures: [{ scope: "recipient" as const, code: "no_active_registration", count: 1 }],
  checked_at: "2026-09-15T10:00:00Z",
};
const clients: QueryClient[] = [];

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const view = render(<QueryClientProvider client={client}>
    <AnnouncementNotificationStatusPanel agencyId="agency-1" groupId="group-1" announcementId="announcement-1" version={2} />
  </QueryClientProvider>);
  const details = view.container.querySelector("details")!;
  return { ...view, details };
}

beforeEach(() => { loadStatus.mockReset(); loadStatus.mockResolvedValue(status); });
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

describe("announcement notification diagnostics", () => {
  it("loads only on expansion, scopes the request, and distinguishes recipients from device evidence", async () => {
    const { details } = renderPanel();
    expect(loadStatus).not.toHaveBeenCalled();
    details.open = true;
    fireEvent(details, new Event("toggle"));
    await screen.findByText("Phone notifications are disabled on the server. The announcement can still appear inside the app.");
    expect(loadStatus).toHaveBeenCalledWith("agency-1", "group-1", "announcement-1", expect.any(AbortSignal));
    expect(screen.getByText(/does not prove that the phone displayed a banner/)).toBeVisible();
    expect(within(screen.getByText("Total recipients").parentElement!).getByText("4")).toBeVisible();
    expect(within(screen.getByText("Total device deliveries").parentElement!).getByText("6")).toBeVisible();
    expect(screen.getByText("Recorded missing device registrations")).toBeVisible();
    expect(screen.getByText(/No registered, authorized device is available/)).toBeVisible();
  });

  it("keeps a failed read visibly unknown and lets an operator retry without publishing", async () => {
    loadStatus.mockRejectedValueOnce({ status: 503, message: "Temporary failure" });
    const { details } = renderPanel();
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Delivery is unknown");
    expect(screen.queryByText("Total recipients")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh notification status" }));
    await screen.findByText("Total recipients");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(loadStatus).toHaveBeenCalledTimes(2);
  });
});
