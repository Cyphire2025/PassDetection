import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { GroupPassengerQrCodes, QrDeliveryPreview } from "../api/operations.api";

const state = vi.hoisted(() => ({
  data: undefined as GroupPassengerQrCodes | undefined, error: null as Error | null,
  generate: vi.fn(), regenerate: vi.fn(), revoke: vi.fn(), expire: vi.fn(), setActive: vi.fn(),
  send: vi.fn(), register: vi.fn(), refetch: vi.fn(),
  gate: null as Promise<void> | null, failed: new Set<string>(), signals: [] as AbortSignal[],
  preview: undefined as QrDeliveryPreview | undefined,
}));
vi.mock("../hooks/use-operations", () => ({
  useGroupQrCodes: () => ({ data: state.data, error: state.error, isLoading: false, refetch: state.refetch }),
  usePassengerQrLifecycle: () => ({ generate: { mutateAsync: state.generate }, regenerate: { mutateAsync: state.regenerate },
    revoke: { mutateAsync: state.revoke }, expire: { mutateAsync: state.expire }, setActive: { mutateAsync: state.setActive } }),
  useQrDeliveryPreview: () => ({ data: state.preview, error: null, isLoading: false }),
  useSendQrBroadcast: () => ({ mutate: state.send, isPending: false, error: null, reset: vi.fn() }),
}));
vi.mock("@/features/whatsapp/components/whatsapp-activity-tracker", () => ({
  useWhatsAppActivityTracker: () => ({ registerActivity: state.register }), WhatsAppActivityInline: () => null,
}));
vi.mock("../services/qr-image-generation", async original => ({
  ...await original<typeof import("../services/qr-image-generation")>(),
  createQrImageGenerator: () => ({ generate: async (entries: Array<[string, string]>, options: {
    signal: AbortSignal; onEntry: (entry: [string, string]) => void;
  }) => {
    state.signals.push(options.signal);
    await state.gate;
    const generated: Array<[string, string]> = [], failedPassengerIds: string[] = [];
    for (const [id] of entries) {
      if (options.signal.aborted) break;
      if (state.failed.has(id)) { failedPassengerIds.push(id); continue; }
      const entry: [string, string] = [id, `data:image/png;base64,synthetic-${id}`];
      generated.push(entry); options.onEntry(entry);
    }
    return { entries: generated, failedPassengerIds };
  } }),
}));

import { TourGroupQrCodesPage } from "./tour-group-qr-codes-page";

function roster(count = 60): GroupPassengerQrCodes {
  return { group_id: "group", group_name: "Synthetic trip", generated_at: "2026-10-31T00:00:00Z",
    passengers: Array.from({ length: count }, (_, index) => ({
      passenger_id: `p${index}`, client_name: `Passenger ${index}`, client_email: null, client_phone: null,
      departure_city: null, coordinator_id: null, coordinator_name: null, qr_status: "active",
      qr_token_version: 1, qr_created_at: null, qr_expires_at: null, qr_revoked_at: null, qr_payload: `synthetic-payload-${index}`,
    })) };
}
beforeEach(() => {
  state.data = roster(); state.error = null; state.gate = null; state.failed = new Set(); state.signals = [];
  state.generate.mockReset().mockResolvedValue({ qr_payload: "synthetic-new-payload" });
  state.regenerate.mockReset().mockResolvedValue({ qr_payload: "synthetic-renewed-payload" });
  state.revoke.mockReset().mockResolvedValue(undefined);
  state.expire.mockReset().mockResolvedValue(undefined);
  state.setActive.mockReset().mockResolvedValue(undefined);
  state.send.mockReset(); state.register.mockReset(); state.refetch.mockReset(); state.preview = undefined;
  vi.spyOn(window, "print").mockReset().mockImplementation(() => undefined);
});

it("reports unavailable roster separately from a successful empty query and supports retry", () => {
  state.data = undefined; state.error = new Error("Synthetic load failure");
  const view = render(<TourGroupQrCodesPage groupId="group" />);
  expect(screen.getByText(/QR codes could not be refreshed/)).toBeVisible();
  expect(screen.queryByText("No submitted passengers are available")).not.toBeInTheDocument();
  expect(screen.getByText("Passenger status unavailable")).toBeVisible();
  expect(screen.queryByText("Loading passengers")).not.toBeInTheDocument();
  expect(screen.getAllByText("—")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Retry QR cards" }));
  expect(state.refetch).toHaveBeenCalledOnce();
  state.error = null; state.data = roster(0);
  view.rerender(<TourGroupQrCodesPage groupId="group" />);
  expect(screen.getByText("No submitted passengers are available")).toBeVisible();
});

it("retains stale cards on refresh failure and filters/paginates the current roster", async () => {
  state.error = new Error("Synthetic refresh failure");
  render(<TourGroupQrCodesPage groupId="group" />);
  expect(screen.getAllByRole("article")).toHaveLength(48);
  fireEvent.click(screen.getByRole("button", { name: "Show next 12 passengers" }));
  expect(screen.getAllByRole("article")).toHaveLength(60);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Passenger 59" } });
  await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
  expect(screen.getByRole("heading", { name: "Passenger 59" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Clear QR search" }));
  await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(48));
});

it("prints the full roster only after every newly revealed image is ready despite a filtered view", async () => {
  render(<TourGroupQrCodesPage groupId="group" />);
  await waitFor(() => expect(screen.getAllByRole("img")).toHaveLength(48));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Passenger 59" } });
  await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
  const gate = Promise.withResolvers<void>(); state.gate = gate.promise;
  fireEvent.click(screen.getByRole("button", { name: "Print all" }));
  expect(screen.getAllByRole("article")).toHaveLength(60);
  expect(window.print).not.toHaveBeenCalled();
  await act(async () => gate.resolve());
  await waitFor(() => expect(window.print).toHaveBeenCalledOnce());
  expect(screen.getAllByRole("article")).toHaveLength(1);
});

it("does not print an incomplete sheet and aborts pending generation when its owner unmounts", async () => {
  state.failed.add("p59");
  const view = render(<TourGroupQrCodesPage groupId="group" />);
  await waitFor(() => expect(screen.getAllByRole("img")).toHaveLength(48));
  fireEvent.click(screen.getByRole("button", { name: "Print all" }));
  await screen.findByText(/print sheet could not be prepared/);
  expect(window.print).not.toHaveBeenCalled();
  const gate = Promise.withResolvers<void>(); state.gate = gate.promise;
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Passenger 59" } });
  await waitFor(() => expect(state.signals.at(-1)?.aborted).toBe(false));
  const pending = state.signals.at(-1)!;
  view.unmount(); expect(pending.aborted).toBe(true);
  await act(async () => gate.resolve());
  expect(window.print).not.toHaveBeenCalled();
});

it("preserves eligible-token selection, trimmed send payload and current activity registration", async () => {
  state.data = roster(2);
  state.preview = { group_id: "group", template_name: "qrcode_v1", template_configured: true, linked_broadcast_count: 1,
    can_send: true, configuration_error: null, message_content: " Synthetic message ",
    summary: { total_passengers: 2, ready: 1, retryable: 0, already_sent: 1, in_progress: 0, blocked: 0 },
    recipients: state.data.passengers.map((passenger, index) => ({ passenger_id: passenger.passenger_id,
      passenger_name: passenger.client_name, passport_number: null, qr_token_id: `t${index}`, qr_token_version: 1,
      qr_status: "active", recipient_id: `r${index}`, broadcast_group_id: "broadcast", broadcast_name: "Synthetic",
      phone_number: "+15550000000", delivery_id: null, delivery_status: index ? "already_sent" : "ready", eligible: !index,
      reason: "Synthetic", error_message: null, message_preview: null })) };
  state.send.mockImplementation((_body, options) => options.onSuccess({ send_batch_id: "batch", queued_count: 1, message: "Synthetic queued" }));
  render(<TourGroupQrCodesPage groupId="group" />);
  fireEvent.click(screen.getByRole("button", { name: "Send WhatsApp Broadcast" }));
  const dialog = screen.getByRole("dialog", { name: "Preview WhatsApp QR delivery" });
  expect(within(dialog).getByRole("checkbox", { name: "Send QR to Passenger 1" })).toBeDisabled();
  fireEvent.click(within(dialog).getByRole("button", { name: "Send individually to 1" }));
  expect(state.send.mock.calls[0][0]).toEqual({ qr_token_ids: ["t0"], message_content: "Synthetic message" });
  expect(state.register).toHaveBeenCalledWith(expect.objectContaining({ id: "batch", kind: "qr", sourceGroupId: "group", total: 1 }));
  expect(within(dialog).getByText(/Synthetic queued/)).toBeVisible();
});

it("keeps both passenger actions pending until their own requests settle", async () => {
  state.data = { ...roster(2), passengers: roster(2).passengers.map(row => ({ ...row, qr_status: "not_generated", qr_payload: null })) };
  const first = Promise.withResolvers<{ qr_payload: string }>(), next = Promise.withResolvers<{ qr_payload: string }>();
  state.generate.mockImplementation(id => id === "p0" ? first.promise : next.promise);
  render(<TourGroupQrCodesPage groupId="group" />);
  const cards = screen.getAllByRole("article");
  fireEvent.click(within(cards[0]).getByRole("button", { name: "Generate QR Code" }));
  fireEvent.click(within(cards[1]).getByRole("button", { name: "Generate QR Code" }));
  try {
    expect(within(cards[0]).getByRole("button")).toBeDisabled();
    expect(within(cards[1]).getByRole("button")).toBeDisabled();
    expect(state.generate).toHaveBeenCalledTimes(2);
    await act(async () => first.resolve({ qr_payload: "synthetic-first" }));
    expect(within(cards[0]).getByRole("button")).toBeEnabled();
    expect(within(cards[1]).getByRole("button")).toBeDisabled();
  } finally {
    await act(async () => { first.resolve({ qr_payload: "synthetic-first" }); next.resolve({ qr_payload: "synthetic-next" }); });
  }
});

it("locks a passenger action synchronously before React commits its pending label", async () => {
  state.data = { ...roster(1), passengers: roster(1).passengers.map(row => ({ ...row, qr_status: "not_generated", qr_payload: null })) };
  const pending = Promise.withResolvers<{ qr_payload: string }>();
  state.generate.mockReturnValue(pending.promise);
  render(<TourGroupQrCodesPage groupId="group" />);
  const button = screen.getByRole("button", { name: "Generate QR Code" });
  act(() => { button.click(); button.click(); });
  try {
    expect(state.generate).toHaveBeenCalledOnce();
  } finally {
    await act(async () => pending.resolve({ qr_payload: "synthetic-new" }));
  }
});

it("preserves lifecycle confirmation and releases a failed row lock for an explicit retry", async () => {
  state.data = roster(1);
  const pending = Promise.withResolvers<void>();
  const confirmation = vi.spyOn(window, "confirm").mockReturnValue(false);
  state.expire.mockReturnValueOnce(pending.promise);
  render(<TourGroupQrCodesPage groupId="group" />);
  const expire = screen.getByRole("button", { name: "Expire now" });
  try {
    fireEvent.click(expire); expect(state.expire).not.toHaveBeenCalled();
    confirmation.mockReturnValue(true);
    act(() => { expire.click(); expire.click(); });
    expect(state.expire).toHaveBeenCalledExactlyOnceWith("p0");
    expect(expire).toBeDisabled();
    await act(async () => pending.reject(new Error("Synthetic lifecycle failure")));
    expect(screen.getByText("The QR status could not be updated. Refresh and try again.")).toBeVisible();
    expect(expire).toBeEnabled();
    fireEvent.click(expire);
    await waitFor(() => expect(state.expire).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(expire).toBeEnabled());
  } finally {
    confirmation.mockRestore();
  }
});
