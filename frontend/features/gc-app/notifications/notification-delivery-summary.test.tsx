import { act, cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotificationDeliverySummary } from "./notification-delivery-summary";
import { agencyId, batch } from "./notification-test-fixtures";
import type { NotificationBatch } from "./notification-types";

vi.mock("./notifications.api", () => ({ notificationsApi: { getBatch: vi.fn(() => new Promise(() => {})) } }));
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); vi.useRealTimers(); });
function setup(value: NotificationBatch) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><NotificationDeliverySummary agencyId={agencyId} batch={value} /></QueryClientProvider>);
}

describe("Notification delivery window", () => {
  it("changes queued and retry labels at expiry while preserving accepted and unknown evidence", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-16T10:04:59Z"));
    const value = { ...batch, device_delivery_counts: { ...batch.device_delivery_counts, retry: 3 } };
    setup(value);
    expect(screen.getByText("Queued").nextSibling).toHaveTextContent("9");
    expect(screen.getByText("Waiting to retry").nextSibling).toHaveTextContent("3");
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(screen.getByText(/Delivery window ended — remaining queued attempts will not be sent/)).toBeVisible();
    expect(screen.getByText("Expired unsent recipients").nextSibling).toHaveTextContent("9");
    expect(screen.getByText("Expired unsent retries").nextSibling).toHaveTextContent("3");
    expect(screen.getByText("Provider accepted; phone display unconfirmed").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Unknown send outcome").nextSibling).toHaveTextContent("1");
    expect(screen.getByText(/Unknown outcomes are not automatically resent/)).toBeVisible();
    expect(value.recipient_counts.queued).toBe(9);
    expect(value.device_delivery_counts.retry).toBe(3);
  });

  it("identifies an already expired batch immediately when opened", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-17T10:00:00Z"));
    setup(batch);
    expect(screen.getByText("Expired unsent recipients")).toBeVisible();
    expect(screen.queryByText("Queued")).not.toBeInTheDocument();
    expect(screen.queryByText("Waiting to retry")).not.toBeInTheDocument();
  });
});
