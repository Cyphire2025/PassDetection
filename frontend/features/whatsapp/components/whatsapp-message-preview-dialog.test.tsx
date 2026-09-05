import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
}));
vi.mock("./whatsapp-dialog-ui", () => ({
  DialogFrame: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ErrorBanner: ({ message }: { message: string }) => (
    <div role="alert">{message}</div>
  ),
  readErrorMessage: (_error: unknown, fallback: string) => fallback,
}));

beforeEach(() => {
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

it("blocks immediate form submission after an edit until the exact new preview succeeds", async () => {
  const user = userEvent.setup();
  const { container, onSend } = renderDialog();
  const send = screen.getByRole("button", { name: "Send individually to 1" });
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
});

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
