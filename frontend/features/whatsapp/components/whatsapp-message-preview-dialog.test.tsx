import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps, ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  WhatsAppBroadcastGroupDetail,
  WhatsAppRecipient,
} from "../api/whatsapp.api";
import { MessagePreviewDialog } from "./whatsapp-message-preview-dialog";

const mocks = vi.hoisted(() => ({
  preview: vi.fn(),
  bulkPreview: vi.fn(),
  detail: {
    id: "group-a",
    name: "Office team",
    recipient_count: 1,
    recipient_opt_in_confirmed: true,
    updated_at: "2026-09-05T00:00:00Z",
    recipients: [
      {
        id: "recipient-a",
        name: "Passenger A",
        normalized_phone_number: "+919999999999",
        message_statuses: [],
      },
    ],
    support_contacts: [],
  } as unknown as WhatsAppBroadcastGroupDetail,
}));
vi.mock("../hooks/use-whatsapp", () => ({
  useWhatsAppGroup: () => ({ data: mocks.detail, isLoading: false }),
  usePreviewWhatsAppMessage: () => ({
    mutate: mocks.preview,
    isPending: false,
  }),
  usePreviewWhatsAppBulkResendMessage: () => ({ mutate: mocks.bulkPreview, isPending: false }),
}));
vi.mock("./whatsapp-dialog-ui", () => ({
  DialogFrame: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ErrorBanner: ({ message }: { message: string }) => (
    <div role="alert">{message}</div>
  ),
  readErrorMessage: (_error: unknown, fallback: string) => fallback,
}));
// The illustration has separate lifecycle tests; exercise the real composer's
// validation and async send boundary with a stable decorative stand-in here.
vi.mock("./whatsapp-broadcast-motion", () => ({
  WhatsAppBroadcastMotion: ({
    messageType,
    state,
    startedAt,
  }: { messageType: string; state: string; startedAt?: number }) => (
    <div
      aria-hidden="true"
      data-testid="broadcast-motion"
      data-message-type={messageType}
      data-state={state}
      data-started-at={startedAt}
    />
  ),
}));

beforeEach(() => {
  mocks.bulkPreview.mockReset();
  mocks.detail = {
    ...mocks.detail,
    recipient_count: 1,
    recipient_opt_in_confirmed: true,
    updated_at: "2026-09-05T00:00:00Z",
    recipients: [recipient("a")],
    support_contacts: [],
  };
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = vi.fn(() => "blob:welcome-image");
      static revokeObjectURL = vi.fn();
    },
  );
  mocks.preview.mockReset().mockImplementation((request, callbacks) =>
    callbacks.onSuccess({
      message_type: request.draft.message_type,
      template_name: `${request.draft.message_type}_v1`,
      recipient_id: request.draft.recipient_id ?? "recipient-a",
      recipient_name: "Passenger A",
      recipient_count: mocks.detail.recipient_count,
      eligible_recipient_count:
        request.draft.recipient_ids?.length ?? mocks.detail.recipient_count,
      already_sent_count: 0,
      in_progress_count: 0,
      uncertain_recipient_count: 0,
      passport_intro:
        request.draft.message_type === "passport_link"
          ? (request.draft.passport_intro ?? "Please upload your documents.")
          : null,
      passport_link:
        request.draft.message_type === "passport_link"
          ? (request.draft.passport_link ?? "https://example.test/upload/group-a")
          : null,
      header_image_id: null,
      message_content: request.draft.message_content ?? "Original reminder",
      content_source: "default",
      rendered_message: request.draft.message_content ?? "Original reminder",
      header_parameter_values: [],
      parameter_values: [],
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

function recipient(suffix: string): WhatsAppRecipient {
  return {
    id: `recipient-${suffix}`,
    name: `Passenger ${suffix.toUpperCase()}`,
    phone_number: "+919999999999",
    normalized_phone_number: "+919999999999",
    imported_fields: {},
    message_statuses: [],
  };
}

function renderDialog(
  props: Partial<ComponentProps<typeof MessagePreviewDialog>> = {},
) {
  const onSend = vi.fn().mockResolvedValue(undefined);
  const view = render(
    <MessagePreviewDialog
      group={mocks.detail}
      messageType="reminder"
      isSending={false}
      onClose={vi.fn()}
      onSend={onSend}
      {...props}
    />,
  );
  return { ...view, onSend };
}

function setupBulkPreview() {
  const selected = [recipient("a"), recipient("b"), recipient("c")].map((item) => ({
    ...item,
    message_statuses: ["welcome", "passport_link"].map((type) => ({
      message_type: type,
      status: item.id === "recipient-c" ? "processing" : "sent",
      already_sent: item.id !== "recipient-c",
      latest_resend_status: null,
      resend_blocked: item.id === "recipient-c",
      submitted_at: null,
      status_updated_at: "2026-09-05T00:00:00Z",
    })),
  }));
  mocks.detail = { ...mocks.detail, recipients: selected, recipient_count: 3, support_contacts: [] };
  mocks.bulkPreview.mockImplementation((request, callbacks) => {
    const id = request.previewRecipientId ?? "recipient-a";
    const wording = request.overrides?.messageContent ?? `Saved wording for ${id}`;
    callbacks.onSuccess({
      message_type: request.messageType,
      template_name: `${request.messageType}_v1`,
      recipient_id: id,
      recipient_name: selected.find((item) => item.id === id)?.name,
      recipient_count: 3,
      selected: 3,
      eligible_recipient_count: 2,
      eligible_recipient_ids: ["recipient-a", "recipient-b"],
      already_sent_count: 2,
      in_progress_count: 1,
      uncertain_recipient_count: 0,
      skipped_no_saved_message: 0,
      skipped_replaced: 0,
      skipped_ineligible: 0,
      skipped_in_progress: 1,
      skipped_delivery_unknown: 0,
      passport_intro: request.messageType === "passport_link" ? request.overrides?.passportIntro ?? `Saved introduction for ${id}` : null,
      passport_link: request.messageType === "passport_link" ? `https://example.test/personal/${id}` : null,
      message_content: wording,
      header_image_id: `saved-image-${id}`,
      content_source: "latest_recipient",
      rendered_message: wording,
      header_parameter_values: [],
      parameter_values: [],
    });
  });
  return selected;
}

it.each(["welcome", "passport_link"] as const)("bulk %s switches saved previews without turning their personal values into shared overrides", async (messageType) => {
  const user = userEvent.setup();
  const bulkRecipients = setupBulkPreview();
  const { onSend } = renderDialog({ messageType, bulkRecipients });
  const send = screen.getByRole("button", { name: "Resend to 0 selected" });
  await waitFor(() => expect(send).toBeEnabled());
  expect(send).toHaveTextContent("Resend to 2 selected");
  const body = screen.getByLabelText(messageType === "welcome" ? "Welcome trip message" : "Passport instructions");
  expect(body).toHaveValue("Saved wording for recipient-a");
  const picker = screen.getByLabelText("Preview recipient");
  expect(Array.from((picker as HTMLSelectElement).options).map((option) => option.value)).toEqual(["recipient-a", "recipient-b"]);
  await user.selectOptions(picker, "recipient-b");
  expect(send).toBeDisabled();
  await waitFor(() => expect(body).toHaveValue("Saved wording for recipient-b"));
  if (messageType === "passport_link") {
    const link = screen.getByLabelText("Passport upload link");
    expect(link).toHaveAttribute("readonly");
    expect(link).toHaveValue("https://example.test/personal/recipient-b");
    expect(screen.getByLabelText("Keep each recipient’s saved support details")).toBeChecked();
    expect(screen.queryByText("All unsent recipients")).not.toBeInTheDocument();
  }
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
  expect(onSend).toHaveBeenCalledWith(expect.objectContaining({
    recipientIds: ["recipient-a", "recipient-b", "recipient-c"],
    headerImage: null,
    bulkDraft: { messageContent: null, passportIntro: null, headerImageId: null, supportContactIds: null },
  }));
  expect(mocks.preview).not.toHaveBeenCalled();
});

it("bulk shared text edits need a fresh preview and preserve personal passport links and saved images", async () => {
  const user = userEvent.setup();
  const bulkRecipients = setupBulkPreview();
  const { container, onSend } = renderDialog({ messageType: "passport_link", bulkRecipients });
  const send = screen.getByRole("button", { name: "Resend to 0 selected" });
  await waitFor(() => expect(send).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Passport instructions"), { target: { value: "Please upload before Friday." } });
  expect(send).toBeDisabled();
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
  await waitFor(() => expect(send).toBeEnabled());
  await user.selectOptions(screen.getByLabelText("Preview recipient"), "recipient-b");
  await waitFor(() => expect(send).toBeEnabled());
  expect(screen.getByLabelText("Passport instructions")).toHaveValue("Please upload before Friday.");
  expect(screen.getByLabelText("Passport upload link")).toHaveValue("https://example.test/personal/recipient-b");
  await user.click(send);
  expect(onSend).toHaveBeenCalledWith(expect.objectContaining({ bulkDraft: {
    messageContent: "Please upload before Friday.", passportIntro: null, headerImageId: null, supportContactIds: null,
  } }));
});

it("an uncertain bulk submission can recover the exact old payload even after its current preview becomes unavailable", async () => {
  const user = userEvent.setup();
  const bulkRecipients = setupBulkPreview();
  const onSend = vi.fn().mockRejectedValueOnce(new Error("Network disconnected")).mockResolvedValue(undefined);
  renderDialog({ messageType: "passport_link", bulkRecipients, onSend });
  const send = screen.getByRole("button", { name: "Resend to 0 selected" });
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
  const recover = await screen.findByRole("button", { name: "Check resend status" });
  mocks.bulkPreview.mockImplementation((_request, callbacks) => callbacks.onError(new Error("All selected sends are in progress")));
  await user.selectOptions(screen.getByLabelText("Preview recipient"), "recipient-b");
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not generate"));
  expect(recover).toBeEnabled();
  await user.click(recover);
  expect(onSend).toHaveBeenCalledTimes(2);
  expect(onSend.mock.calls[1][0]).toEqual(onSend.mock.calls[0][0]);
});

it("editing an uncertain bulk draft disables recovery of the previous wording", async () => {
  const user = userEvent.setup();
  const bulkRecipients = setupBulkPreview();
  const onSend = vi.fn().mockRejectedValueOnce(new Error("Network disconnected"));
  renderDialog({ messageType: "welcome", bulkRecipients, onSend });
  const send = screen.getByRole("button", { name: "Resend to 0 selected" });
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
  await screen.findByRole("button", { name: "Check resend status" });
  fireEvent.change(screen.getByLabelText("Welcome trip message"), { target: { value: "A different welcome message" } });
  expect(screen.queryByRole("button", { name: "Check resend status" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeDisabled();
  await waitFor(() => expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeEnabled());
  expect(onSend).toHaveBeenCalledTimes(1);
});

it("blocks immediate form submission after an edit until the exact new preview succeeds", async () => {
  const user = userEvent.setup();
  const { container, onSend } = renderDialog();
  const send = screen.getByRole("button", { name: "Send individually to 1" });
  expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();
  await waitFor(() => expect(send).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Reminder paragraph"), {
    target: { value: "Updated reminder" },
  });
  expect(send).toBeDisabled();
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
  expect(onSend).toHaveBeenCalledWith(
    expect.objectContaining({ messageContent: "Updated reminder" }),
  );
});

it("never reuses an older successful preview after the changed draft preview fails", async () => {
  const successfulPreview = mocks.preview.getMockImplementation()!;
  const user = userEvent.setup();
  const { container, onSend } = renderDialog();
  const send = screen.getByRole("button", { name: "Send individually to 1" });
  await waitFor(() => expect(send).toBeEnabled());
  mocks.preview.mockImplementation((_request, callbacks) =>
    callbacks.onError(new Error("Provider unavailable")),
  );
  fireEvent.change(screen.getByLabelText("Reminder paragraph"), {
    target: { value: "Unverified text" },
  });
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("Could not generate"),
  );
  expect(send).toBeDisabled();
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
  mocks.preview.mockImplementation(successfulPreview);
  await user.click(screen.getByRole("button", { name: "Retry preview" }));
  await waitFor(() => expect(send).toBeEnabled());
});

it("requires a welcome image and a fresh preview after selecting a valid 5 MB image", async () => {
  const successfulPreview = mocks.preview.getMockImplementation()!;
  const user = userEvent.setup();
  const { container, onSend } = renderDialog({ messageType: "welcome" });
  const send = screen.getByRole("button", { name: "Send individually to 1" });
  await screen.findByText("Original reminder", { selector: "span" });
  expect(send).toBeDisabled();
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
  expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();

  // Hold the replacement preview so the last successful text preview cannot
  // authorize a newly selected image, even if the form is submitted directly.
  mocks.preview.mockImplementation(() => undefined);
  const image = new File([new Uint8Array(5 * 1024 * 1024)], "welcome.png", {
    type: "image/png",
  });
  await user.upload(screen.getByLabelText(/Welcome image/), image);
  expect(send).toBeDisabled();
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
  expect(URL.createObjectURL).toHaveBeenCalledWith(image);

  mocks.preview.mockImplementation(successfulPreview);
  await user.click(screen.getByRole("button", { name: "Retry preview" }));
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
  expect(onSend).toHaveBeenCalledWith(
    expect.objectContaining({ headerImage: image, headerImageId: null }),
  );
});

it.each([
  ["oversized PNG", "image/png", 5 * 1024 * 1024 + 1, "5 MB or smaller"],
  ["unsupported image", "image/webp", 20, "Use a JPEG or PNG"],
])(
  "rejects an %s before sending a welcome message",
  async (_case, type, size, error) => {
    const { container, onSend } = renderDialog({ messageType: "welcome" });
    fireEvent.change(screen.getByLabelText(/Welcome image/), {
      target: {
        files: [new File([new Uint8Array(size)], "welcome.image", { type })],
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(error);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Send individually to 1" }),
    ).toBeDisabled();
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).not.toHaveBeenCalled();
  },
);

it("preserves custom recipients across searches and sends only the selected support contact", async () => {
  const user = userEvent.setup();
  mocks.detail.recipients.push(recipient("b"));
  mocks.detail.recipient_count = 2;
  mocks.detail.support_contacts = [
    {
      id: "support-a",
      name: "Trip coordinator",
      phone_number: "+918888888888",
      normalized_phone_number: "+918888888888",
    },
    {
      id: "support-b",
      name: "Travel desk",
      phone_number: "+917777777777",
      normalized_phone_number: "+917777777777",
    },
  ];
  const { container, onSend } = renderDialog({ messageType: "passport_link" });
  const image = new File(["image"], "passport-link.jpg", {
    type: "image/jpeg",
  });
  await user.upload(screen.getByLabelText(/Passport Link image/), image);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Send individually to 2" }),
    ).toBeEnabled(),
  );

  await user.click(screen.getByRole("radio", { name: "Custom select" }));
  expect(screen.getByRole("checkbox", { name: /Passenger A/ })).toBeChecked();
  const search = screen.getByRole("searchbox", {
    name: "Search recipients by name or phone",
  });
  await user.type(search, "Passenger B");
  await user.click(screen.getByRole("checkbox", { name: /Passenger B/ }));
  await user.clear(search);
  expect(screen.getByRole("checkbox", { name: /Passenger A/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Passenger B/ })).toBeChecked();
  await user.click(screen.getByRole("checkbox", { name: /Passenger A/ }));
  await user.click(screen.getByRole("radio", { name: /Travel desk/ }));
  expect(screen.getByRole("radio", { name: /Trip coordinator/ })).not.toBeChecked();

  const send = screen.getByRole("button", { name: "Send individually to 1" });
  expect(send).toBeDisabled();
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
  await waitFor(() => expect(send).toBeEnabled());
  expect(mocks.preview).toHaveBeenLastCalledWith(
    expect.objectContaining({
      draft: expect.objectContaining({
        recipient_ids: ["recipient-b"],
        support_contact_ids: ["support-b"],
      }),
    }),
    expect.any(Object),
  );
  await user.click(send);
  expect(onSend).toHaveBeenCalledWith({
    passportIntro: "Please upload your documents.",
    passportLink: "https://example.test/upload/group-a",
    messageContent: "Original reminder",
    headerImage: image,
    headerImageId: null,
    recipientIds: ["recipient-b"],
    supportContactIds: ["support-b"],
  });
});

it("keeps a passport link unsendable when no support contact is configured", async () => {
  const user = userEvent.setup();
  const { container, onSend } = renderDialog({ messageType: "passport_link" });
  await user.upload(
    screen.getByLabelText(/Passport Link image/),
    new File(["image"], "passport-link.jpg", { type: "image/jpeg" }),
  );
  await screen.findByDisplayValue("Please upload your documents.");
  expect(screen.getByText(/no customer support contacts/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Send individually to 1" }),
  ).toBeDisabled();
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
  expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();
});

it.each(["welcome", "passport_link", "reminder"] as const)(
  "starts %s motion immediately on a validated send and keeps it through pending updates",
  async (messageType) => {
    const user = userEvent.setup();
    if (messageType === "passport_link") {
      mocks.detail.support_contacts = [{
        id: "support-a",
        name: "Travel desk",
        phone_number: "+918888888888",
        normalized_phone_number: "+918888888888",
      }];
    }
    let completeSend!: () => void;
    const onSend = vi.fn(() => new Promise<void>((resolve) => { completeSend = resolve; }));
    const props = { group: mocks.detail, messageType, onSend, onClose: vi.fn() };
    const { container, rerender } = renderDialog(props);
    expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();
    if (messageType !== "reminder") {
      await user.upload(
        screen.getByLabelText(messageType === "welcome" ? /Welcome image/ : /Passport Link image/),
        new File(["image"], "message.jpg", { type: "image/jpeg" }),
      );
    }
    const send = screen.getByRole("button", { name: "Send individually to 1" });
    await waitFor(() => expect(send).toBeEnabled());
    expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();
    await user.click(send);

    const motion = screen.getByTestId("broadcast-motion");
    expect(motion).toHaveAttribute("data-message-type", messageType);
    expect(motion).toHaveAttribute("data-state", "submitting");
    expect(Number(motion.getAttribute("data-started-at"))).toBeGreaterThan(0);
    expect(screen.getByText("Submitting your messages...")).toBeVisible();
    expect(send).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).toHaveBeenCalledTimes(1);

    rerender(<MessagePreviewDialog {...props} isSending />);
    expect(screen.getByTestId("broadcast-motion")).toBe(motion);
    rerender(<MessagePreviewDialog {...props} isSending={false} />);
    expect(screen.getByTestId("broadcast-motion")).toBe(motion);
    await act(async () => completeSend());
    expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();
    expect(send).toBeEnabled();
  },
);

it("stops submission motion on request failure and allows a fresh attempt", async () => {
  const user = userEvent.setup();
  let failSend!: (error: Error) => void;
  const onSend = vi.fn(() => new Promise<void>((_resolve, reject) => { failSend = reject; }));
  renderDialog({ onSend });
  const send = screen.getByRole("button", { name: "Send individually to 1" });
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
  expect(screen.getByTestId("broadcast-motion")).toBeVisible();
  await act(async () => failSend(new Error("Unavailable")));
  expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("could not submit");
  expect(send).toBeEnabled();
  onSend.mockResolvedValueOnce(undefined);
  await user.click(send);
  expect(onSend).toHaveBeenCalledTimes(2);
});

it.each(["retry", "resend"] as const)(
  "shows motion immediately for a validated single-recipient %s",
  async (action) => {
    const user = userEvent.setup();
    mocks.detail.recipients[0].message_statuses = [{
      message_type: "reminder",
      status: action === "retry" ? "failed" : "sent",
      already_sent: action === "resend",
      resend_blocked: false,
      latest_resend_status: null,
      submitted_at: null,
      status_updated_at: "2026-09-06T00:00:00Z",
    }];
    let completeSend!: () => void;
    const onSend = vi.fn(() => new Promise<void>((resolve) => { completeSend = resolve; }));
    renderDialog({
      onSend,
      targetRecipient: {
        recipientId: "recipient-a",
        recipientName: "Passenger A",
        phoneNumber: "+919999999999",
        messageType: "reminder",
        action,
      },
    });
    const send = screen.getByRole("button", { name: `${action === "retry" ? "Retry" : "Resend"} to Passenger A` });
    await waitFor(() => expect(send).toBeEnabled());
    expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();
    await user.click(send);
    expect(screen.getByTestId("broadcast-motion")).toHaveAttribute("data-state", "submitting");
    expect(onSend).toHaveBeenCalledTimes(1);
    await act(async () => completeSend());
    expect(screen.queryByTestId("broadcast-motion")).not.toBeInTheDocument();
  },
);

it("revokes a one-person retry when the recipient's latest delivery is no longer failed", async () => {
  const status = {
    message_type: "reminder",
    status: "failed",
    already_sent: false,
    latest_resend_status: null,
    resend_blocked: false,
    submitted_at: null,
    status_updated_at: "2026-09-06T00:00:00Z",
  };
  mocks.detail.recipients[0].message_statuses = [status];
  const targetRecipient = {
    recipientId: "recipient-a",
    recipientName: "Passenger A",
    phoneNumber: "+919999999999",
    messageType: "reminder" as const,
    action: "retry" as const,
  };
  const { container, onSend, rerender } = renderDialog({ targetRecipient });
  const send = screen.getByRole("button", { name: "Retry to Passenger A" });
  await waitFor(() => expect(send).toBeEnabled());
  expect(mocks.preview).toHaveBeenLastCalledWith(
    expect.objectContaining({
      draft: expect.objectContaining({
        resend_recipient_id: "recipient-a",
        recipient_id: null,
      }),
    }),
    expect.any(Object),
  );

  mocks.detail = {
    ...mocks.detail,
    updated_at: "2026-09-06T00:01:00Z",
    recipients: [
      {
        ...mocks.detail.recipients[0],
        message_statuses: [{ ...status, status: "queued" }],
      },
    ],
  };
  rerender(
    <MessagePreviewDialog
      group={mocks.detail}
      messageType="reminder"
      targetRecipient={targetRecipient}
      isSending={false}
      onClose={vi.fn()}
      onSend={onSend}
    />,
  );
  expect(send).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "latest delivery state changed",
  );
  fireEvent.submit(container.querySelector("form")!);
  expect(onSend).not.toHaveBeenCalled();
});
