import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  WhatsAppBroadcastGroupDetail,
  WhatsAppMessageDraft,
  WhatsAppPreviewResponse,
  WhatsAppRecipient,
} from "../api/whatsapp.api";
import { MessagePreviewDialog } from "./whatsapp-message-preview-dialog";
import { WhatsAppPage } from "./whatsapp-workspace";

const mocks = vi.hoisted(() => ({
  detail: {} as WhatsAppBroadcastGroupDetail,
  preview: vi.fn(),
  bulkPreview: vi.fn(),
  sendReminder: vi.fn(),
  sendWelcome: vi.fn(),
  sendPassportLink: vi.fn(),
  registerActivity: vi.fn(),
  latestReminder: "Please meet the coordinator at 9 AM.",
  eligibleCount: 3,
  inProgressCount: 0,
  alreadySentCount: 0,
  uncertainCount: 0,
}));

// Keep the real workspace menu, lazy composer, modal, editor and send boundary.
// Only data/provider hooks and the separately tested activity illustration are
// replaced. No preview or send can reach the network in these tests.
vi.mock("../hooks/use-whatsapp", () => ({
  useWhatsAppGroups: () => ({ data: [mocks.detail], isLoading: false }),
  useWhatsAppGroup: () => ({ data: mocks.detail, isLoading: false }),
  useCreateWhatsAppGroup: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteWhatsAppGroup: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSendWhatsAppWelcome: () => ({ mutateAsync: mocks.sendWelcome, isPending: false }),
  useSendWhatsAppPassportLink: () => ({ mutateAsync: mocks.sendPassportLink, isPending: false }),
  useSendWhatsAppReminder: () => ({ mutateAsync: mocks.sendReminder, isPending: false }),
  usePreviewWhatsAppMessage: () => ({ mutate: mocks.preview, isPending: false }),
  usePreviewWhatsAppBulkResendMessage: () => ({ mutate: mocks.bulkPreview, isPending: false }),
}));
vi.mock("./whatsapp-activity-tracker", () => ({
  useWhatsAppActivityTracker: () => ({ activities: [], registerActivity: mocks.registerActivity }),
  WhatsAppActivityInline: () => null,
}));
vi.mock("./whatsapp-broadcast-motion", () => ({ WhatsAppBroadcastMotion: () => null }));

function recipient(status: string, index: number): WhatsAppRecipient {
  return {
    id: `recipient-${index}`,
    name: `Example ${status}`,
    phone_number: `+1555000000${index}`,
    normalized_phone_number: `+1555000000${index}`,
    imported_fields: {},
    message_statuses: status === "new" ? [] : [{
      message_type: "reminder",
      status,
      already_sent: ["sent", "delivered", "read"].includes(status),
      latest_resend_status: null,
      resend_blocked: ["queued", "processing", "delivery_unknown"].includes(status),
      submitted_at: "2026-09-09T08:00:00Z",
      status_updated_at: "2026-09-09T08:01:00Z",
    }],
  };
}

function setRecipients(statuses: string[]) {
  mocks.detail = {
    id: "reminder-group",
    name: "Example travel team",
    recipient_count: statuses.length,
    total_contact_count: statuses.length,
    recipient_opt_in_confirmed: true,
    created_at: "2026-09-01T08:00:00Z",
    updated_at: "2026-09-09T08:01:00Z",
    recipients: statuses.map(recipient),
    support_contacts: [],
    rejected_contact_count: 0,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  setRecipients(["sent", "delivered", "read"]);
  mocks.latestReminder = "Please meet the coordinator at 9 AM.";
  mocks.eligibleCount = 3;
  mocks.inProgressCount = 0;
  mocks.alreadySentCount = 0;
  mocks.uncertainCount = 0;
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:synthetic-header");
    static revokeObjectURL = vi.fn();
  });
  mocks.preview.mockImplementation((
    request: { groupId: string; draft: WhatsAppMessageDraft },
    callbacks: { onSuccess: (response: WhatsAppPreviewResponse) => void },
  ) => {
    const selected = mocks.detail.recipients.find((item) => item.id === request.draft.recipient_id)
      ?? mocks.detail.recipients[0];
    const message = request.draft.message_content ?? mocks.latestReminder;
    callbacks.onSuccess({
      message_type: request.draft.message_type,
      template_name: "approved_reminder_template",
      recipient_id: selected?.id ?? "",
      recipient_name: selected?.name ?? "",
      recipient_count: mocks.detail.recipient_count,
      eligible_recipient_count: mocks.eligibleCount,
      already_sent_count: mocks.alreadySentCount,
      in_progress_count: mocks.inProgressCount,
      uncertain_recipient_count: mocks.uncertainCount,
      passport_intro: null,
      passport_link: null,
      header_image_id: null,
      message_content: message,
      content_source: "latest_group",
      rendered_message: `Dear ${selected?.name},\n${message}\nGlobal Connect Travels`,
      header_parameter_values: [],
      parameter_values: [selected?.name ?? "", message],
    });
  });
  mocks.sendReminder.mockImplementation(async ({ messageContent }: { messageContent: string }) => {
    mocks.latestReminder = messageContent;
    return {
      batch_id: `reminder-batch-${mocks.sendReminder.mock.calls.length}`,
      queued: mocks.eligibleCount,
      sent: 0,
      failed: 0,
      delivery_unknown: 0,
      skipped_already_sent: 0,
      skipped_in_progress: mocks.inProgressCount,
      skipped_delivery_unknown: 0,
      results: [],
    };
  });
});

afterEach(() => vi.unstubAllGlobals());

async function openReminder(user: ReturnType<typeof userEvent.setup>, surface = 0) {
  const menu = screen.getAllByRole("button", { name: "Open actions for Example travel team" })[surface];
  await user.click(menu);
  const reminder = await screen.findByRole("button", { name: "Send Reminder" });
  expect(reminder).toBeEnabled();
  await user.click(reminder);
  const dialog = await screen.findByRole("dialog", { name: "Edit Reminder" });
  const send = within(dialog).getByRole("button", { name: /Send individually to/ });
  await waitFor(() => expect(send).toBeEnabled());
  return { dialog, send, paragraph: within(dialog).getByLabelText("Reminder paragraph") };
}

it("opens the editor before every reminder and supports cancel, edit, send, reopen and another send to everyone", async () => {
  const user = userEvent.setup();
  render(<WhatsAppPage />);
  const cancelled = await openReminder(user);
  expect(mocks.sendReminder).not.toHaveBeenCalled();
  fireEvent.change(cancelled.paragraph, { target: { value: "This discarded draft must not be sent." } });
  await user.click(within(cancelled.dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(mocks.sendReminder).not.toHaveBeenCalled();

  for (const [index, wording] of ["The coach leaves at 10 AM.", "Please bring your room key to checkout."].entries()) {
    const previewCalls = mocks.preview.mock.calls.length;
    // Exercise each real workspace menu surface across the two sends.
    const { dialog, send, paragraph } = await openReminder(user, index);
    expect(mocks.preview.mock.calls.length).toBeGreaterThan(previewCalls);
    expect(paragraph).toHaveValue(mocks.latestReminder);
    expect(mocks.sendReminder).toHaveBeenCalledTimes(index);
    expect(send).toHaveTextContent("Send individually to 3");
    expect(within(dialog).getByText(/including people who received earlier reminders/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/remaining recipients/)).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/previous recipients? will be skipped/)).not.toBeInTheDocument();

    fireEvent.change(paragraph, { target: { value: wording } });
    expect(send).toBeDisabled();
    fireEvent.submit(dialog.querySelector("form")!);
    expect(mocks.sendReminder).toHaveBeenCalledTimes(index);
    await waitFor(() => expect(send).toBeEnabled());
    expect(within(dialog).getByTestId("whatsapp-message-preview")).toHaveTextContent(wording);
    await user.click(send);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocks.sendReminder).toHaveBeenNthCalledWith(index + 1, {
      groupId: "reminder-group", messageContent: wording, recipientIds: null,
    });
  }
  expect(mocks.registerActivity).toHaveBeenCalledTimes(2);
  expect(mocks.sendWelcome).not.toHaveBeenCalled();
  expect(mocks.sendPassportLink).not.toHaveBeenCalled();
  expect(mocks.bulkPreview).not.toHaveBeenCalled();
});

it("keeps earlier terminal reminders in the audience and preview list while using the server count for active deliveries", async () => {
  setRecipients(["sent", "delivered", "read", "failed", "delivery_unknown", "new", "queued", "processing"]);
  mocks.eligibleCount = 6;
  mocks.inProgressCount = 2;
  // A mixed-version response must not produce once-only reminder copy.
  mocks.alreadySentCount = 3;
  mocks.uncertainCount = 1;
  const user = userEvent.setup();
  render(<WhatsAppPage />);
  const { dialog, send } = await openReminder(user);
  expect(send).toHaveTextContent("Send individually to 6");
  expect(within(dialog).getByText("6 eligible of 8")).toBeInTheDocument();
  expect(within(dialog).getByText(/2 recipients are already queued and will not be queued twice/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/will be skipped automatically/)).not.toBeInTheDocument();
  expect(within(dialog).queryByText(/unknown delivery outcome and require review/)).not.toBeInTheDocument();
  const picker = within(dialog).getByLabelText("Preview recipient") as HTMLSelectElement;
  expect(Array.from(picker.options, (option) => option.value)).toEqual(mocks.detail.recipients.map((item) => item.id));
  await user.selectOptions(picker, "recipient-4");
  await waitFor(() => expect(send).toBeEnabled());
  expect(within(dialog).getByTestId("whatsapp-message-preview")).toHaveTextContent("Dear Example delivery_unknown");
  await user.click(send);
  expect(mocks.sendReminder).toHaveBeenCalledWith(expect.objectContaining({ recipientIds: null }));
});

it("does not allow another reminder while every recipient has an active delivery", async () => {
  setRecipients(["queued", "processing"]);
  mocks.eligibleCount = 0;
  mocks.inProgressCount = 2;
  render(<MessagePreviewDialog group={mocks.detail} messageType="reminder" isSending={false} onClose={vi.fn()} onSend={mocks.sendReminder} />);
  await screen.findByText(/A reminder is still being sent to 2 recipients/);
  const send = screen.getByRole("button", { name: "Send individually to 0" });
  expect(send).toBeDisabled();
  fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
  expect(mocks.sendReminder).not.toHaveBeenCalled();
  expect(screen.queryByText(/already been sent successfully to every recipient/)).not.toBeInTheDocument();
});
