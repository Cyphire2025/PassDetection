import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { WhatsAppBroadcastGroup } from "../api/whatsapp.api";
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
  },
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
  mocks.preview.mockReset().mockImplementation((request, callbacks) =>
    callbacks.onSuccess({
      message_type: "reminder",
      template_name: "reminder_v1",
      recipient_id: "recipient-a",
      recipient_name: "Passenger A",
      recipient_count: 1,
      eligible_recipient_count: 1,
      already_sent_count: 0,
      in_progress_count: 0,
      uncertain_recipient_count: 0,
      passport_intro: null,
      passport_link: null,
      header_image_id: null,
      message_content: request.draft.message_content ?? "Original reminder",
      content_source: "default",
      rendered_message: request.draft.message_content ?? "Original reminder",
      header_parameter_values: [],
      parameter_values: [],
    }),
  );
});

function renderDialog() {
  const onSend = vi.fn().mockResolvedValue(undefined);
  const view = render(
    <MessagePreviewDialog
      group={mocks.detail as unknown as WhatsAppBroadcastGroup}
      messageType="reminder"
      isSending={false}
      onClose={vi.fn()}
      onSend={onSend}
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
