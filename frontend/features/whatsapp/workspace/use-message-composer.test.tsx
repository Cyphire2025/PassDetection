import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { UncertainWhatsAppSendError } from "../utils/normal-send-storage";
import type { MessageDefinition } from "./composer.api";
import { useMessageComposer } from "./use-message-composer";

const mocks = vi.hoisted(() => ({
  group: {} as WhatsAppBroadcastGroupDetail,
  preview: {} as Record<string, unknown>,
  data: {} as Record<string, unknown>,
  debounce: null as string | null,
  lastDraft: "",
  enabled: false,
  pending: false,
  mutate: vi.fn(),
  push: vi.fn(),
  register: vi.fn(),
}));
vi.mock("./broadcast-workspace-shell", () => ({ useBroadcast: () => mocks.group }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("../hooks/use-normal-send", () => ({
  useNormalWhatsAppSend: () => ({ mutateAsync: mocks.mutate, isPending: mocks.pending }),
}));
vi.mock("../components/whatsapp-activity-tracker", () => ({
  useWhatsAppActivityTracker: () => ({ registerActivity: mocks.register }),
}));
vi.mock("../components/whatsapp-dialog-ui", () => ({
  readErrorMessage: (error: Error) => error.message,
}));
vi.mock("@/hooks/use-debounce", () => ({
  useDebounce: (key: string) => { mocks.lastDraft = key; return mocks.debounce ?? key; },
}));
vi.mock("@tanstack/react-query", () => ({
  keepPreviousData: (value: unknown) => value,
  useQuery: (options: { enabled: boolean }) => {
    mocks.enabled = options.enabled;
    return { data: options.enabled ? mocks.data : undefined, ...mocks.preview };
  },
}));

const definition: MessageDefinition = {
  id: "reminder", message_type: "reminder", label: "Reminder", description: "Trip reminder",
  category: "Trip", image_required: false, audience: "reminder", repeatable: true,
  fields: [{ key: "message_content", label: "Message", kind: "textarea", required: true, max_length: 1000 }],
};
const response = { batch_id: "batch/1", queued: 1, sent: 0, failed: 0, delivery_unknown: 0 };
beforeEach(() => {
  vi.clearAllMocks();
  mocks.debounce = null;
  mocks.pending = false;
  mocks.preview = { isFetching: false, isPlaceholderData: false, error: null };
  mocks.data = { rendered_message: "Reviewed reminder", message_content: "Meet at 9", template_name: "reminder_v1", eligible_recipient_count: 1 };
  mocks.group = {
    id: "broadcast", name: "Synthetic group", is_archived: false, recipient_count: 1,
    total_contact_count: 1, recipient_opt_in_confirmed: true, created_at: "2026-01-01",
    updated_at: "2026-01-01", rejected_contact_count: 0, support_contacts: [],
    recipients: [{ id: "person", name: "Test person", phone_number: "+919000000001",
      normalized_phone_number: "+919000000001", imported_fields: {}, message_statuses: [],
      welcome_status: "delivered", welcome_delivered: true }],
  };
  mocks.mutate.mockResolvedValue(response);
});

describe("current broadcast composer safety gates", () => {
  it("derives a large selected audience with bounded membership work and original ordering", () => {
    const size = 512;
    const first = mocks.group.recipients[0];
    mocks.group.recipients = Array.from({ length: size }, (_, index) => ({
      ...first,
      id: `person-${index}`,
      normalized_phone_number: `+919${String(index).padStart(9, "0")}`,
    }));
    mocks.data.eligible_recipient_count = size;
    let numericReads = 0;
    const ids = mocks.group.recipients.map((recipient) => recipient.id).reverse();
    const selectedIds = new Proxy(ids, {
      get(target, property, receiver) {
        if (typeof property === "string" && /^\d+$/.test(property)) numericReads += 1;
        return Reflect.get(target, property, receiver);
      },
    });
    const { result } = renderHook(() => useMessageComposer(definition));
    act(() => result.current.setState((state) => ({ ...state, recipientIds: selectedIds })));
    expect(result.current.selected.map((recipient) => recipient.id)).toEqual([...ids].reverse());
    expect(result.current.selectedIds).toBe(selectedIds);
    expect(result.current.ready).toBe(true);
    expect(numericReads).toBeLessThanOrEqual(4 * size);
  });

  it.each(["fetching", "placeholder", "error", "no template", "welcome required", "no consent", "archived", "pending", "no audience"])("does not dispatch when %s", async (state) => {
    if (state === "fetching") mocks.preview.isFetching = true;
    if (state === "placeholder") mocks.preview.isPlaceholderData = true;
    if (state === "error") mocks.preview.error = new Error("Preview unavailable");
    if (state === "no template") mocks.data.template_name = null;
    if (state === "welcome required") mocks.data.welcome_required_count = 1;
    if (state === "no consent") mocks.group.recipient_opt_in_confirmed = false;
    if (state === "archived") mocks.group.is_archived = true;
    if (state === "pending") mocks.pending = true;
    if (state === "no audience") mocks.data.audience_recipient_ids = [];
    const { result } = renderHook(() => useMessageComposer(definition));
    expect(result.current.ready).toBe(false);
    await act(() => result.current.send());
    expect(mocks.mutate).not.toHaveBeenCalled();
  });

  it("invalidates a reviewed preview immediately when text changes before debounce", async () => {
    const { result } = renderHook(() => useMessageComposer(definition));
    expect(result.current.ready).toBe(true);
    mocks.debounce = mocks.lastDraft;
    act(() => result.current.setState((state) => ({ ...state, fields: { message_content: "Changed text" } })));
    expect(result.current.current).toBe(false);
    await act(() => result.current.send());
    expect(mocks.mutate).not.toHaveBeenCalled();
  });

  it("requires an unambiguous active submission group for not-submitted reminders", () => {
    mocks.group.linked_client_groups = [{ id: "first", name: "First", status: "active" }, { id: "second", name: "Second", status: "active" }];
    const { result } = renderHook(() => useMessageComposer(definition));
    act(() => result.current.setState((state) => ({ ...state, reminderAudience: "not_submitted" })));
    expect(mocks.enabled).toBe(false);
    expect(result.current.ready).toBe(false);
    act(() => result.current.setState((state) => ({ ...state, reminderGroupId: "second" })));
    expect(mocks.enabled).toBe(true);
    expect(JSON.parse(mocks.lastDraft)).toMatchObject({ audience: "not_submitted", audience_client_group_id: "second" });
  });

  it("does not send an explicitly empty selection even when preview supplies an eligible count", async () => {
    const { result } = renderHook(() => useMessageComposer(definition));
    act(() => result.current.setState((state) => ({ ...state, recipientIds: [] })));
    expect(result.current.count).toBe(0);
    await act(() => result.current.send());
    expect(mocks.mutate).not.toHaveBeenCalled();
  });

  it("locks rapid duplicate submits and registers only the accepted durable batch", async () => {
    let resolve!: (value: typeof response) => void;
    mocks.mutate.mockReturnValue(new Promise((done) => { resolve = done; }));
    const { result } = renderHook(() => useMessageComposer(definition));
    let first!: Promise<void>;
    act(() => { first = result.current.send(); void result.current.send(); });
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
    await act(async () => { resolve(response); await first; });
    expect(mocks.register).toHaveBeenCalledWith(expect.objectContaining({ id: "batch/1", kind: "broadcast", sourceGroupId: "broadcast", title: "Reminder", total: 1 }));
    expect(mocks.push).toHaveBeenCalledWith(expect.stringContaining("?message=batch%2F1"));
  });

  it("retries the exact unconfirmed request and reviewed snapshot after later edits", async () => {
    mocks.mutate.mockRejectedValueOnce(new Error("Connection lost"));
    const { result } = renderHook(() => useMessageComposer(definition));
    await act(() => result.current.send());
    const original = mocks.mutate.mock.calls[0][0];
    act(() => result.current.setState((state) => ({ ...state, fields: { message_content: "Different draft" } })));
    expect(result.current.reviewedMessage).toBe("Reviewed reminder");
    await act(() => result.current.send(true));
    expect(mocks.mutate.mock.calls[1][0]).toBe(original);
    expect(original.draft.message_content).toBe("Meet at 9");
  });

  it("requires the explicit separate-message action after an uncertain different intent", async () => {
    const startNew = vi.fn();
    mocks.mutate.mockRejectedValueOnce(new UncertainWhatsAppSendError(startNew));
    const { result } = renderHook(() => useMessageComposer(definition));
    await act(() => result.current.send());
    expect(result.current.uncertain).toBeInstanceOf(UncertainWhatsAppSendError);
    expect(result.current.recovery).toBeNull();
    expect(startNew).not.toHaveBeenCalled();
    act(() => result.current.startSeparateMessage());
    expect(startNew).toHaveBeenCalledOnce();
    expect(result.current.uncertain).toBeNull();
  });
});
