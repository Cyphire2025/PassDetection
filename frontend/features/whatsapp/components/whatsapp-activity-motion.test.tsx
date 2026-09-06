import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ROUTES } from "@/constants/routes";
import type { WhatsAppActivitySummary } from "../api/whatsapp-activity.api";
import {
  initialWhatsAppActivitySummary,
  parseTrackedWhatsAppActivities,
  type TrackedWhatsAppActivity,
  WHATSAPP_ACTIVITY_POSITION_KEY,
  WHATSAPP_ACTIVITY_STORAGE_KEY,
} from "../utils/activity-tracking";
import {
  useWhatsAppActivityTracker,
  WhatsAppActivityInline,
  WhatsAppActivityTrackerProvider,
} from "./whatsapp-activity-tracker";

const mocks = vi.hoisted(() => ({
  pathname: "/whatsapp",
  summary: vi.fn(),
  failures: vi.fn(),
}));
vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));
vi.mock("../api/whatsapp-activity.api", () => ({
  whatsappActivityApi: { summary: mocks.summary, failures: mocks.failures },
}));

const activity: TrackedWhatsAppActivity = {
  id: "batch-a",
  kind: "broadcast",
  startedAt: 1_789_000_000_000,
  title: "Passport link broadcast",
  contextLabel: "Office team",
  sourceGroupId: "group-a",
  documentType: null,
  messageType: "passport_link",
  total: 16,
  queued: 16,
  sent: 0,
  failed: 0,
  deliveryUnknown: 0,
};
const queryKey = ["whatsapp", "activities", "broadcast", activity.id];
const clients: QueryClient[] = [];

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  mocks.pathname = ROUTES.dashboard.whatsapp;
  mocks.summary.mockReset().mockImplementation(() => new Promise(() => {}));
  mocks.failures.mockReset().mockResolvedValue([
    { recipient_name: "Passenger A", phone_number: "+919999999999", error_message: "Provider rejected the request" },
  ]);
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    disconnect() {}
  });
});

afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
});

function CurrentPage() {
  const { registerActivity } = useWhatsAppActivityTracker();
  return (
    <>
      <button onClick={() => registerActivity(activity)}>Register broadcast</button>
      {mocks.pathname === ROUTES.dashboard.whatsapp
        ? <WhatsAppActivityInline />
        : <p>Another dashboard page</p>}
    </>
  );
}

function renderTracker() {
  const client = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
  clients.push(client);
  const tree = () => (
    <QueryClientProvider client={client}>
      <WhatsAppActivityTrackerProvider><CurrentPage /></WhatsAppActivityTrackerProvider>
    </QueryClientProvider>
  );
  const view = render(tree());
  return { ...view, client, navigate: (pathname: string) => {
    mocks.pathname = pathname;
    view.rerender(tree());
  } };
}

function scene() {
  return document.querySelector('[data-whatsapp-broadcast-motion="true"]');
}

async function update(client: QueryClient, values: Partial<WhatsAppActivitySummary>) {
  act(() => client.setQueryData(queryKey, { ...initialWhatsAppActivitySummary(activity), ...values }));
  await waitFor(() => expect(screen.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow", String(16 - (values.queued ?? 16)),
  ));
}

it("starts from the registered batch immediately and keeps the same scene through progress and completion", async () => {
  const { client } = renderTracker();
  fireEvent.click(screen.getByRole("button", { name: "Register broadcast" }));
  const original = scene();
  expect(original).not.toBeNull();
  expect(original).toHaveAttribute("data-state", "sending");
  expect(original).toHaveAttribute("data-message-type", "passport_link");
  expect(screen.getByText("0 sent of 16")).toBeVisible();
  expect(parseTrackedWhatsAppActivities(window.sessionStorage.getItem(WHATSAPP_ACTIVITY_STORAGE_KEY))[0])
    .toMatchObject({ messageType: "passport_link", startedAt: activity.startedAt });

  await update(client, { sent: 8, queued: 8 });
  expect(scene()).toBe(original);
  expect(screen.getByText("8 sent of 16")).toBeVisible();
  await update(client, { sent: 8, queued: 8 });
  expect(scene()).toBe(original);
  await update(client, { sent: 16, queued: 0 });
  expect(scene()).toBe(original);
  expect(original).toHaveAttribute("data-state", "complete");
  expect(screen.queryByText(/delivered|read by/i)).not.toBeInTheDocument();
});

it("carries the same broadcast into the floating tracker and back, preserving counts and actionable failures", async () => {
  const { client, navigate } = renderTracker();
  fireEvent.click(screen.getByRole("button", { name: "Register broadcast" }));
  await update(client, { sent: 8, queued: 8 });
  navigate("/dashboard/another-page");
  const floating = screen.getByLabelText("Movable WhatsApp delivery progress");
  const floatingScene = scene();
  expect(floating).toContainElement(floatingScene as HTMLElement);
  expect(floatingScene).toHaveAttribute("data-message-type", "passport_link");
  expect(screen.getByText("8 sent of 16")).toBeVisible();
  await update(client, { sent: 12, queued: 4 });
  expect(scene()).toBe(floatingScene);

  navigate(ROUTES.dashboard.whatsapp);
  expect(screen.queryByLabelText("Movable WhatsApp delivery progress")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Live WhatsApp delivery progress")).toContainElement(scene() as HTMLElement);
  expect(screen.getByText("12 sent of 16")).toBeVisible();
  navigate("/dashboard/another-page");
  const terminalScene = scene();
  await update(client, { sent: 14, queued: 0, failed: 1, delivery_unknown: 1 });
  expect(scene()).toBe(terminalScene);
  expect(scene()).toHaveAttribute("data-state", "attention");
  expect(screen.getByText(/1 delivery outcome is unknown and need review/)).toBeVisible();
  expect(mocks.failures).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Show 1 failed recipients" }));
  expect(await screen.findByText("Passenger A")).toBeVisible();
  expect(screen.getByText("Provider rejected the request")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Close Passport link broadcast progress" }));
  expect(scene()).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Movable WhatsApp delivery progress")).not.toBeInTheDocument();
});

it("settles the existing scene during a status-fetch error and resumes it after recovery", async () => {
  const { client } = renderTracker();
  fireEvent.click(screen.getByRole("button", { name: "Register broadcast" }));
  await update(client, { sent: 8, queued: 8 });
  const original = scene();
  act(() => client.getQueryCache().find({ queryKey })!.setState({
    error: new Error("Status temporarily unavailable"), status: "error", fetchStatus: "idle",
  }));
  await waitFor(() => expect(original).toHaveAttribute("data-state", "reconnecting"));
  expect(scene()).toBe(original);
  expect(screen.getByText("Reconnecting")).toBeVisible();
  expect(screen.getByText("8 sent of 16")).toBeVisible();
  await update(client, { sent: 9, queued: 7 });
  expect(scene()).toBe(original);
  expect(original).toHaveAttribute("data-state", "sending");
});

it("restores old stored broadcasts with generic artwork while document and QR rows retain their existing UI", () => {
  window.sessionStorage.setItem(WHATSAPP_ACTIVITY_STORAGE_KEY, JSON.stringify([
    { ...activity, messageType: undefined },
    { ...activity, id: "document-a", kind: "document", title: "Visa documents", messageType: undefined },
    { ...activity, id: "qr-a", kind: "qr", title: "QR messages", messageType: undefined },
  ]));
  renderTracker();
  expect(document.querySelectorAll('[data-whatsapp-broadcast-motion="true"]')).toHaveLength(1);
  expect(scene()).toHaveAttribute("data-message-type", "broadcast");
  expect(screen.getAllByRole("progressbar")).toHaveLength(3);
});

it("keeps the animated floating tracker draggable and clamps it within the viewport", async () => {
  vi.stubGlobal("PointerEvent", class extends MouseEvent {
    pointerId: number;
    constructor(type: string, options: PointerEventInit) {
      super(type, options);
      this.pointerId = options.pointerId ?? 1;
    }
  });
  window.sessionStorage.setItem(WHATSAPP_ACTIVITY_STORAGE_KEY, JSON.stringify([activity]));
  mocks.pathname = "/dashboard/another-page";
  renderTracker();
  const floating = screen.getByLabelText("Movable WhatsApp delivery progress");
  floating.setPointerCapture = vi.fn();
  floating.hasPointerCapture = vi.fn(() => true);
  floating.releasePointerCapture = vi.fn();
  vi.spyOn(floating, "getBoundingClientRect").mockReturnValue({
    x: 500, y: 500, left: 500, top: 500, right: 920, bottom: 610, width: 420, height: 110,
    toJSON: () => ({}),
  });
  const pointer = { button: 0, pointerId: 1, clientX: 520, clientY: 520 };
  fireEvent.pointerDown(screen.getByRole("button", { name: "Close Passport link broadcast progress" }), pointer);
  expect(floating.setPointerCapture).not.toHaveBeenCalled();
  fireEvent.pointerDown(scene()!, pointer);
  fireEvent.pointerMove(floating, { ...pointer, clientX: 3000, clientY: 3000 });
  fireEvent.pointerUp(floating, { ...pointer, clientX: 3000, clientY: 3000 });
  await waitFor(() => expect(floating).toHaveStyle({
    left: `${window.innerWidth - 420 - 16}px`, top: `${window.innerHeight - 110 - 16}px`,
  }));
  expect(floating.releasePointerCapture).toHaveBeenCalledWith(1);
  expect(JSON.parse(window.localStorage.getItem(WHATSAPP_ACTIVITY_POSITION_KEY)!)).toEqual({
    x: window.innerWidth - 420 - 16, y: window.innerHeight - 110 - 16,
  });
});

it.each(["welcome", "passport_link", "reminder", "unrecognised", null, 42, undefined])(
  "restores only supported motion metadata from stored messageType %s",
  (messageType) => {
    const [restored] = parseTrackedWhatsAppActivities(JSON.stringify([{ ...activity, messageType }]));
    expect(restored.id).toBe(activity.id);
    expect(restored.messageType).toBe(
      ["welcome", "passport_link", "reminder"].includes(String(messageType)) ? messageType : undefined,
    );
  },
);
