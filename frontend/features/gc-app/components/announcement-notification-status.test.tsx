import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAnnouncementNotificationStatus, type AnnouncementNotificationStatus } from "../api/announcement-notification-status.api";
import { AnnouncementNotificationStatusPanel } from "./announcement-notification-status";

vi.mock("../api/announcement-notification-status.api", () => ({
  getAnnouncementNotificationStatus: vi.fn(),
}));

const loadStatus = vi.mocked(getAnnouncementNotificationStatus);
const status: AnnouncementNotificationStatus = {
  announcement_id: "announcement-1", provider_enabled: false,
  recipient_counts: { total: 4, queued: 2, sent: 1, failed: 1, cancelled: 0, read: 2, no_active_registration: 1, unknown: 0 },
  device_delivery_counts: { total: 6, submitting: 1, retry: 1, receipt_pending: 2, delivered: 1, failed: 1, cancelled: 0, provider_accepted: 0, unknown: 0 },
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

  it("distinguishes an unavailable status read from an unknown send and lets the operator refresh", async () => {
    loadStatus.mockRejectedValueOnce({ status: 503, message: "Temporary failure" });
    const { details } = renderPanel();
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The latest delivery status is unavailable");
    expect(screen.queryByText("Total recipients")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh notification status" }));
    await screen.findByText("Total recipients");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(loadStatus).toHaveBeenCalledTimes(2);
  });

  it("keeps Google acceptance separate from phone display and does not offer a resend for unknown outcomes", async () => {
    loadStatus.mockResolvedValue({
      ...status, provider_enabled: true,
      recipient_counts: { ...status.recipient_counts, total: 5, queued: 0, sent: 2, unknown: 2 },
      device_delivery_counts: { ...status.device_delivery_counts, total: 11, provider_accepted: 3, unknown: 2 },
      failures: [{ scope: "device", code: "provider_outcome_unknown", count: 2 }],
    });
    const { details } = renderPanel();
    details.open = true;
    fireEvent(details, new Event("toggle"));
    await screen.findByText("Accepted by Google; phone display unconfirmed");
    expect(within(screen.getByText("Accepted by Google; phone display unconfirmed").parentElement!).getByText("3")).toBeVisible();
    expect(within(screen.getByText("Provider receipt received; phone display unconfirmed").parentElement!).getByText("1")).toBeVisible();
    expect(within(screen.getByText("Recipients with an unknown send outcome").parentElement!).getByText("2")).toBeVisible();
    expect(within(screen.getByText("Unknown send outcome; not automatically resent").parentElement!).getByText("2")).toBeVisible();
    expect(screen.getByText(/unknown outcome are not automatically resent, to avoid duplicate alerts/)).toBeVisible();
    expect(screen.getByText(/The send outcome is unknown; no automatic resend will be attempted/)).toBeVisible();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Refresh notification status" })).toBeVisible();
    expect(screen.queryByText(/Phone notifications are disabled/)).not.toBeInTheDocument();
  });

  it.each([
    ["fcm_connection_unavailable", "The server could not connect to Google"],
    ["fcm_quota_exceeded", "Google's sending limit was reached"],
    ["fcm_unavailable", "Google's notification service is unavailable"],
    ["DeviceNotRegistered", "The device registration is no longer valid; open the app to register again"],
    ["fcm_sender_id_mismatch", "The device registration belongs to a different Firebase project"],
    ["fcm_authentication_failed", "Google rejected the server credentials or permissions"],
    ["fcm_invalid_argument", "Google rejected the notification format or device registration"],
    ["fcm_provider_rejected", "Google rejected the notification request"],
    ["fcm_credentials_missing", "Firebase server credentials are missing; contact the administrator"],
    ["fcm_credentials_invalid", "Firebase server credentials are invalid; contact the administrator"],
    ["fcm_credentials_project_or_type_mismatch", "Firebase server credentials do not match the configured project or account type"],
    ["fcm_credentials_path_must_be_absolute", "The Firebase server credential file location is not configured correctly"],
    ["fcm_credentials_unavailable", "The server could not use the Firebase credentials; contact the administrator"],
    ["private-provider-error-with-token", "Another notification problem was recorded"],
  ])("explains %s without exposing raw provider details", async (code, label) => {
    loadStatus.mockResolvedValue({ ...status, failures: [{ scope: "device", code, count: 1 }] });
    const { details } = renderPanel();
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await screen.findByText(`${label}: 1 (device deliveries)`)).toBeVisible();
    expect(screen.queryByText(new RegExp(code))).not.toBeInTheDocument();
  });
});
