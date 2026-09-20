import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatsAppBroadcastGroupDetail, WhatsAppMessageDraft, WhatsAppPreviewResponse, WhatsAppRecipient } from "../api/whatsapp.api";
import { MessagePreviewDialog } from "./whatsapp-message-preview-dialog";

const mocks = vi.hoisted(() => ({ detail: {} as WhatsAppBroadcastGroupDetail, preview: vi.fn(), bulkPreview: vi.fn() }));
vi.mock("../hooks/use-whatsapp", () => ({
  useWhatsAppGroup: () => ({ data: mocks.detail, isLoading: false }),
  usePreviewWhatsAppMessage: () => ({ mutate: mocks.preview, isPending: false }),
  usePreviewWhatsAppBulkResendMessage: () => ({ mutate: mocks.bulkPreview, isPending: false }),
}));
vi.mock("./whatsapp-dialog-ui", () => ({
  DialogFrame: ({ children, title }: { children: ReactNode; title: string }) => <div><h1>{title}</h1>{children}</div>,
  ErrorBanner: ({ message }: { message: string }) => <p role="alert">{message}</p>,
  readErrorMessage: (_error: unknown, fallback: string) => fallback,
}));

const link = "https://chat.whatsapp.com/InviteAbC123?mode=ac_t";
const recipient = (id: string): WhatsAppRecipient => ({ id, name: `Delegate ${id}`, phone_number: "+919999999999", normalized_phone_number: "+919999999999", imported_fields: {}, message_statuses: [], welcome_delivered: true });
function preview(draft: WhatsAppMessageDraft): WhatsAppPreviewResponse {
  const message = draft.message_content ?? "Please join our official travel group.";
  const invitation = draft.group_invite_link ?? link;
  return {
    message_type: "group_invite", template_name: "whatsapp_group_invite_v1", recipient_id: draft.recipient_id ?? draft.recipient_ids?.[0] ?? "A", recipient_name: "Delegate A", recipient_count: 2,
    eligible_recipient_count: draft.recipient_ids?.length ?? 2, already_sent_count: 0, in_progress_count: 0, uncertain_recipient_count: 0,
    passport_intro: null, passport_link: null, group_invite_link: invitation, message_content: message, header_image_id: null, content_source: "default",
    rendered_message: `Dear Delegates\n\nGreetings from Global Connect Travels\n\n${message}\n\n${invitation}\n\nRegards\nTeam Global Connect Travels`,
    header_parameter_values: [], parameter_values: [message, invitation],
  };
}
function mount(props: Partial<ComponentProps<typeof MessagePreviewDialog>> = {}) {
  const onSend = vi.fn().mockResolvedValue(undefined);
  const view = render(<MessagePreviewDialog group={mocks.detail} messageType="group_invite" isSending={false} onClose={vi.fn()} onSend={onSend} {...props} />);
  return { ...view, onSend };
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.detail = { id: "group-1", name: "Delegates", recipient_count: 2, total_contact_count: 2, recipient_opt_in_confirmed: true, created_at: "2026-09-20", updated_at: "2026-09-20", recipients: [recipient("A"), recipient("B")], support_contacts: [], rejected_contact_count: 0 };
  mocks.preview.mockImplementation(({ draft }, callbacks) => callbacks.onSuccess(preview(draft)));
  mocks.bulkPreview.mockImplementation(({ overrides, recipientIds, previewRecipientId }, callbacks) => callbacks.onSuccess({
    ...preview({ message_type: "group_invite", message_content: overrides.messageContent, group_invite_link: overrides.groupInviteLink, recipient_id: previewRecipientId }),
    selected: recipientIds.length, eligible_recipient_ids: recipientIds, skipped_no_saved_message: 0, skipped_replaced: 0, skipped_ineligible: 0, skipped_in_progress: 0, skipped_delivery_unknown: 0,
  }));
});

describe("group invite composer", () => {
  it("shows the exact text template, no unrelated controls, and sends edited content with the query-bearing invite link", async () => {
    const { onSend } = mount();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send individually to 2" })).toBeEnabled());
    expect(screen.getByTestId("whatsapp-message-preview").textContent).toBe(preview({ message_type: "group_invite" }).rendered_message);
    expect(screen.queryByText(/header image/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/passport/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Customer support")).not.toBeInTheDocument();
    expect(screen.queryByText("Reminder audience")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Invitation message"), { target: { value: "Join for departure updates." } });
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send individually to 2" })).toBeEnabled());
    expect(screen.getByTestId("whatsapp-message-preview")).toHaveTextContent("Join for departure updates.");
    fireEvent.click(screen.getByRole("button", { name: "Send individually to 2" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledWith(expect.objectContaining({ messageContent: "Join for departure updates.", groupInviteLink: link, headerImage: null, headerImageId: null, supportContactIds: null, recipientIds: null })));
  });

  it("blocks invalid official links and empty content even if preview service accepts them", async () => {
    const { onSend, container } = mount();
    await screen.findByDisplayValue(link);
    fireEvent.change(screen.getByLabelText("WhatsApp group invite link"), { target: { value: "https://chat.whatsapp.com.evil.test/Invite" } });
    await waitFor(() => expect(mocks.preview).toHaveBeenLastCalledWith(expect.objectContaining({ draft: expect.objectContaining({ group_invite_link: "https://chat.whatsapp.com.evil.test/Invite" }) }), expect.any(Object)));
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("WhatsApp group invite link"), { target: { value: link } });
    fireEvent.change(screen.getByLabelText("Invitation message"), { target: { value: "   " } });
    await waitFor(() => expect(mocks.preview).toHaveBeenLastCalledWith(expect.objectContaining({ draft: expect.objectContaining({ message_content: "   " }) }), expect.any(Object)));
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
  });

  it("reconciles preview B when changing to a custom audience containing only A", async () => {
    const { onSend } = mount();
    await screen.findByDisplayValue(link);
    fireEvent.change(screen.getByLabelText("Preview recipient"), { target: { value: "B" } });
    await waitFor(() => expect(mocks.preview).toHaveBeenLastCalledWith(expect.objectContaining({ draft: expect.objectContaining({ recipient_id: "B" }) }), expect.any(Object)));
    fireEvent.click(screen.getByLabelText("Choose recipients"));
    fireEvent.click(screen.getByRole("checkbox", { name: /Delegate A/ }));
    await waitFor(() => expect(mocks.preview).toHaveBeenLastCalledWith(expect.objectContaining({ draft: expect.objectContaining({ recipient_id: null, recipient_ids: ["A"] }) }), expect.any(Object)));
    await waitFor(() => expect(screen.getByRole("button", { name: "Send individually to 1" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send individually to 1" }));
    expect(onSend).toHaveBeenCalledWith(expect.objectContaining({ recipientIds: ["A"] }));
  });

  it("never lets an old preview authorize changed wording", async () => {
    let oldSuccess!: (value: WhatsAppPreviewResponse) => void;
    mocks.preview.mockImplementationOnce((_request, callbacks) => { oldSuccess = callbacks.onSuccess; });
    mount();
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Invitation message"), { target: { value: "New invitation" } });
    act(() => oldSuccess(preview({ message_type: "group_invite", message_content: "Old invitation" })));
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    await waitFor(() => expect(screen.getByTestId("whatsapp-message-preview")).toHaveTextContent("New invitation"));
    expect(screen.getByTestId("whatsapp-message-preview")).not.toHaveTextContent("Old invitation");
  });

  it.each(["archived", "opt-in", "welcome"])("keeps the existing %s guardrail", async (guard) => {
    if (guard === "archived") mocks.detail.is_archived = true;
    if (guard === "opt-in") mocks.detail.recipient_opt_in_confirmed = false;
    if (guard === "welcome") mocks.preview.mockImplementation(({ draft }, callbacks) => callbacks.onSuccess({ ...preview(draft), welcome_required_count: 1, welcome_required_reason: "Welcome must be delivered first." }));
    const { onSend, container } = mount();
    await screen.findByDisplayValue(link);
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeVisible();
  });

  it("keeps each bulk recipient's saved link unless explicitly edited, and safely retries an uncertain request", async () => {
    const onSend = vi.fn().mockRejectedValueOnce(new Error("Connection lost")).mockResolvedValue(undefined);
    mount({ bulkRecipients: mocks.detail.recipients, onSend });
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Resend to 2 selected" }));
    await screen.findByRole("button", { name: "Check resend status" });
    expect(onSend).toHaveBeenLastCalledWith(expect.objectContaining({ recipientIds: ["A", "B"], bulkDraft: { messageContent: null, groupInviteLink: null } }));
    fireEvent.click(screen.getByRole("button", { name: "Check resend status" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    expect(onSend.mock.calls[0][0]).toEqual(onSend.mock.calls[1][0]);
    fireEvent.change(screen.getByLabelText("WhatsApp group invite link"), { target: { value: "https://chat.whatsapp.com/Replacement123" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Resend to 2 selected" }));
    expect(onSend).toHaveBeenLastCalledWith(expect.objectContaining({ bulkDraft: { messageContent: null, groupInviteLink: "https://chat.whatsapp.com/Replacement123" } }));
  });
});
