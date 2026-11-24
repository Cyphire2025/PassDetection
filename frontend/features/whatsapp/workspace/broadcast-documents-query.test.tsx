import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { documentDistributionApi } from "@/features/documents/api/document-distribution.api";
import { composerApi } from "./composer.api";
import { BroadcastDocumentsPage } from "./broadcast-documents-page";
import { syntheticBroadcastLinks, syntheticBroadcastReview } from "./broadcast-document-fixtures.test-fixture";

vi.mock("./broadcast-workspace-shell", () => ({
  useBroadcast: () => ({ id: "broadcast", is_archived: false,
    linked_client_groups: [{ id: "trip", name: "Synthetic trip" }] }),
}));
vi.mock("./composer.api", () => ({ composerApi: { passengerLinks: vi.fn() } }));
vi.mock("@/features/documents/api/document-distribution.api", () => ({
  documentDistributionApi: { getReview: vi.fn() },
}));

const clients: QueryClient[] = [];
beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(composerApi.passengerLinks).mockReset().mockResolvedValue(syntheticBroadcastLinks);
  vi.mocked(documentDistributionApi.getReview).mockReset().mockResolvedValue(syntheticBroadcastReview);
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.useRealTimers();
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return render(<QueryClientProvider client={client}><BroadcastDocumentsPage /></QueryClientProvider>);
}

async function tick(duration: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(duration); });
}

it.each([401, 403, 404].flatMap(status => ["links", "review"].map(target => ({ status, target }))))(
  "stops $target interval requests after $status and permits an explicit refresh",
  async ({ status, target }) => {
    const denial = { status, code: "SYNTHETIC_DENIAL", message: "Synthetic access denial" };
    if (target === "links") {
      vi.mocked(composerApi.passengerLinks).mockResolvedValueOnce(syntheticBroadcastLinks).mockRejectedValue(denial);
    } else {
      vi.mocked(documentDistributionApi.getReview).mockResolvedValueOnce(syntheticBroadcastReview).mockRejectedValue(denial);
    }
    mount();
    await tick(0);
    expect(screen.getByRole("button", { name: "Send documents" })).toBeEnabled();
    await tick(20_001);
    const requests = () => target === "links"
      ? vi.mocked(composerApi.passengerLinks).mock.calls.length
      : vi.mocked(documentDistributionApi.getReview).mock.calls.length;
    expect(requests()).toBe(2);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await tick(60_000);
    expect(requests()).toBe(2);
    vi.mocked(composerApi.passengerLinks).mockResolvedValue(syntheticBroadcastLinks);
    vi.mocked(documentDistributionApi.getReview).mockResolvedValue(syntheticBroadcastReview);
    fireEvent.click(screen.getByRole("button", { name: "Refresh documents" }));
    await tick(0);
    expect(requests()).toBe(3);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send documents" })).toBeEnabled();
  },
);

it("requires a successfully refreshed document review before opening delivery from stale rows", async () => {
  vi.mocked(documentDistributionApi.getReview).mockResolvedValueOnce(syntheticBroadcastReview)
    .mockRejectedValue({ status: 403, code: "SYNTHETIC_DENIAL" });
  mount();
  await tick(0);
  expect(screen.getByRole("button", { name: "Send documents" })).toBeEnabled();
  await tick(20_001);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send documents" })).toBeDisabled();
});

it("does not describe an unavailable initial review as a zero-document count", async () => {
  vi.mocked(documentDistributionApi.getReview).mockRejectedValue({ status: 403, code: "SYNTHETIC_DENIAL" });
  mount();
  await tick(0);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "All (unavailable)" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "All (0)" })).not.toBeInTheDocument();
});

it("recovers from a temporary server failure without requiring a manual refresh", async () => {
  vi.mocked(documentDistributionApi.getReview).mockResolvedValueOnce(syntheticBroadcastReview)
    .mockRejectedValueOnce({ status: 503, code: "SYNTHETIC_UNAVAILABLE" })
    .mockResolvedValue(syntheticBroadcastReview);
  mount();
  await tick(0);
  await tick(20_001);
  await tick(25_000);
  expect(documentDistributionApi.getReview).toHaveBeenCalledTimes(3);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send documents" })).toBeEnabled();
});

it("counts and filters a large roster with bounded document-status work and the same visible rows", async () => {
  const size = 512;
  let statusReads = 0;
  const document = { ...syntheticBroadcastReview.review_rows[0].documents[0] };
  Object.defineProperty(document, "delivery_status", {
    enumerable: true,
    get: () => { statusReads += 1; return "not_sent"; },
  });
  const rows = Array.from({ length: size }, (_, index) => ({
    ...syntheticBroadcastReview.review_rows[0], passenger_id: `person-${index}`,
    passenger_name: `Synthetic passenger ${index}`, document, documents: [document],
  }));
  vi.mocked(documentDistributionApi.getReview).mockResolvedValue({
    ...syntheticBroadcastReview, review_rows: rows,
  });
  vi.mocked(composerApi.passengerLinks).mockResolvedValue(rows.map(row => ({
    group_id: "trip", passenger_id: row.passenger_id,
  })));
  mount();
  await tick(0);
  statusReads = 0;
  fireEvent.change(screen.getByLabelText("Search passenger documents"), { target: { value: "Synthetic" } });
  await tick(0);
  for (const [label, count] of [["All", size], ["Multiple PDFs", 0], ["Shared PDF", size],
    ["Assigned", size], ["Missing", 0], ["Sent", 0], ["Not sent", size]]) {
    expect(screen.getByRole("button", { name: `${label} (${count})` })).toBeInTheDocument();
  }
  expect(screen.getAllByRole("row")).toHaveLength(51);
  expect(screen.getByText("Synthetic passenger 0")).toBeInTheDocument();
  expect(statusReads).toBeLessThanOrEqual((4 * size) + 100);
});
