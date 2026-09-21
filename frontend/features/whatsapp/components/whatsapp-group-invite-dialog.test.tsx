import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
  readErrorMessage: (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback,
}));

const link = "https://chat.whatsapp.com/InviteAbC123?mode=ac_t";
const recipient = (id: string): WhatsAppRecipient => ({ id, name: `Delegate ${id}`, phone_number: "+919999999999", normalized_phone_number: "+919999999999", imported_fields: {}, message_statuses: [], welcome_delivered: false, welcome_status: "required", welcome_required_reason: "Welcome must arrive first." });
function preview(draft: WhatsAppMessageDraft): WhatsAppPreviewResponse {
  const message = draft.message_content ?? "Please join our official travel group.";
  const invitation = draft.group_invite_link ?? link;
  return {
    message_type: "group_invite", template_name: "whatsapp_group_invite_v1", recipient_id: draft.recipient_id ?? draft.recipient_ids?.[0] ?? "A", recipient_name: "Delegate A", recipient_count: 2,
    eligible_recipient_count: draft.recipient_ids?.length ?? 2, already_sent_count: 0, in_progress_count: 0, uncertain_recipient_count: 0,
    passport_intro: null, passport_link: null, group_invite_link: invitation, message_content: message, header_image_id: "saved-invite-photo", content_source: "default",
    rendered_message: `Dear Delegates\n\nGreetings from Global Connect Travels\n\n${message}\n\n${invitation}\n\nRegards\nTeam Global Connect Travels`,
    header_parameter_values: [], parameter_values: [message, invitation],
  };
}
function mount(props: Partial<ComponentProps<typeof MessagePreviewDialog>> = {}) {
  const onSend = vi.fn().mockResolvedValue(undefined);
  const view = render(<MessagePreviewDialog group={mocks.detail} messageType="group_invite" isSending={false} onClose={vi.fn()} onSend={onSend} {...props} />);
  return { ...view, onSend };
}
const photo = (name = "invitation.png") => new File(["photo"], name, { type: "image/png" });
function selectPhoto(file = photo()) {
  fireEvent.change(screen.getByLabelText("Group invite photo"), { target: { files: [file] } });
  return file;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn((file: File) => `blob:${file.name}`);
    static revokeObjectURL = vi.fn();
  });
  mocks.detail = { id: "group-1", name: "Delegates", recipient_count: 2, total_contact_count: 2, recipient_opt_in_confirmed: true, created_at: "2026-09-20", updated_at: "2026-09-20", recipients: [recipient("A"), recipient("B")], support_contacts: [], rejected_contact_count: 0 };
  mocks.preview.mockImplementation(({ draft }, callbacks) => callbacks.onSuccess(preview(draft)));
  mocks.bulkPreview.mockImplementation(({ overrides, recipientIds, previewRecipientId }, callbacks) => callbacks.onSuccess({
    ...preview({ message_type: "group_invite", message_content: overrides.messageContent, group_invite_link: overrides.groupInviteLink, recipient_id: previewRecipientId }),
    selected: recipientIds.length, eligible_recipient_ids: recipientIds, skipped_no_saved_message: 0, skipped_replaced: 0, skipped_ineligible: 0, skipped_in_progress: 0, skipped_delivery_unknown: 0, missing_header_image_count: 0,
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("group invite composer", () => {
  it("sends a first invitation without welcome delivery while requiring a photo and valid message", async () => {
    mocks.preview.mockImplementation(({ draft }, callbacks) => callbacks.onSuccess({ ...preview(draft), header_image_id: null }));
    const { onSend } = mount();
    await screen.findByDisplayValue(link);
    expect(screen.getByRole("button", { name: "Send individually to 2" })).toBeDisabled();
    expect(screen.getByTestId("whatsapp-message-preview").textContent).toBe(preview({ message_type: "group_invite" }).rendered_message);
    const image = selectPhoto();
    expect(screen.getByAltText("Selected Group invite image header")).toHaveAttribute("src", "blob:invitation.png");
    expect(screen.queryByLabelText(/passport/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Customer support")).not.toBeInTheDocument();
    expect(screen.queryByText("Reminder audience")).not.toBeInTheDocument();
    expect(screen.queryByText(/welcome/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Invitation message"), { target: { value: "Join for departure updates." } });
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send individually to 2" })).toBeEnabled());
    expect(screen.getByTestId("whatsapp-message-preview")).toHaveTextContent("Join for departure updates.");
    fireEvent.click(screen.getByRole("button", { name: "Send individually to 2" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledWith(expect.objectContaining({ messageContent: "Join for departure updates.", groupInviteLink: link, headerImage: image, headerImageId: null, supportContactIds: null, recipientIds: null })));
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

  it.each(["archived", "opt-in"])("keeps the existing %s guardrail", async (guard) => {
    if (guard === "archived") mocks.detail.is_archived = true;
    if (guard === "opt-in") mocks.detail.recipient_opt_in_confirmed = false;
    const { onSend, container } = mount();
    await screen.findByDisplayValue(link);
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeVisible();
  });

  it("allows bulk invitation resends without welcome delivery and safely recovers the same request", async () => {
    const onSend = vi.fn().mockRejectedValueOnce(new Error("Connection lost")).mockResolvedValue(undefined);
    mount({ bulkRecipients: mocks.detail.recipients, onSend });
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeEnabled());
    expect(screen.queryByText(/welcome/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resend to 2 selected" }));
    await screen.findByRole("button", { name: "Check resend status" });
    expect(onSend).toHaveBeenLastCalledWith(expect.objectContaining({ recipientIds: ["A", "B"], headerImage: null, headerImageId: null, bulkDraft: { messageContent: null, groupInviteLink: null, headerImageId: null } }));
    fireEvent.click(screen.getByRole("button", { name: "Check resend status" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    expect(onSend.mock.calls[0][0]).toEqual(onSend.mock.calls[1][0]);
    fireEvent.change(screen.getByLabelText("WhatsApp group invite link"), { target: { value: "https://chat.whatsapp.com/Replacement123" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Resend to 2 selected" }));
    expect(onSend).toHaveBeenLastCalledWith(expect.objectContaining({ bulkDraft: { messageContent: null, groupInviteLink: "https://chat.whatsapp.com/Replacement123", headerImageId: null } }));
  });

  it("allows a single resend without welcome and never revives a removed photo without explicit reset", async () => {
    mocks.detail.recipients[0].message_statuses = [{ message_type: "group_invite", status: "delivered", already_sent: true, latest_resend_status: null, resend_blocked: false, submitted_at: null, status_updated_at: "2026-09-21" }];
    const { onSend, container } = mount({ targetRecipient: { recipientId: "A", recipientName: "Delegate A", phoneNumber: "+919999999999", messageType: "group_invite", action: "resend" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to Delegate A" })).toBeEnabled());
    expect(screen.queryByText(/welcome/i)).not.toBeInTheDocument();
    expect(screen.getByText("Saved message image")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Remove photo" }));
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Resend to Delegate A" })).toBeDisabled();
    expect(screen.queryByText("Saved message image")).not.toBeInTheDocument();
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Use saved photo" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to Delegate A" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Resend to Delegate A" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledWith(expect.objectContaining({ headerImage: null, headerImageId: "saved-invite-photo" })));
  });

  it("allows a failed invitation retry without welcome delivery", async () => {
    mocks.detail.recipients[0].message_statuses = [{ message_type: "group_invite", status: "failed", already_sent: false, latest_resend_status: null, resend_blocked: false, submitted_at: null, status_updated_at: "2026-09-21" }];
    const { onSend } = mount({ targetRecipient: { recipientId: "A", recipientName: "Delegate A", phoneNumber: "+919999999999", messageType: "group_invite", action: "retry" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry to Delegate A" })).toBeEnabled());
    expect(screen.queryByText(/welcome/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry to Delegate A" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
  });

  it("keeps a blocked single resend unavailable even without the welcome prerequisite", async () => {
    mocks.detail.recipients[0].message_statuses = [{ message_type: "group_invite", status: "sent", already_sent: true, latest_resend_status: "processing", resend_blocked: true, submitted_at: null, status_updated_at: "2026-09-21" }];
    const { onSend, container } = mount({ targetRecipient: { recipientId: "A", recipientName: "Delegate A", phoneNumber: "+919999999999", messageType: "group_invite", action: "resend" } });
    await screen.findByDisplayValue(link);
    expect(screen.getByRole("button", { name: "Resend to Delegate A" })).toBeDisabled();
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).not.toHaveBeenCalled();
  });

  it.each([
    { name: "invalid type", file: () => new File(["gif"], "animated.gif", { type: "image/gif" }), message: "Use a JPEG or PNG photo." },
    { name: "oversized photo", file: () => new File([new Uint8Array(5 * 1024 * 1024 + 1)], "large.png", { type: "image/png" }), message: "The photo must be 5 MB or smaller." },
  ])("rejects $name without allowing a saved image to hide the error", async ({ file, message }) => {
    const { onSend, container } = mount();
    await screen.findByDisplayValue(link);
    selectPhoto(file());
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    fireEvent.submit(container.querySelector("form")!);
    expect(onSend).not.toHaveBeenCalled();
    selectPhoto();
    await waitFor(() => expect(screen.getByRole("button", { name: "Send individually to 2" })).toBeEnabled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("invalidates a checked preview when replacing a photo and releases each local preview URL", async () => {
    const { onSend, unmount } = mount();
    await screen.findByDisplayValue(link);
    const first = selectPhoto(photo("first.png"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Send individually to 2" })).toBeEnabled());
    let latestSuccess!: (response: WhatsAppPreviewResponse) => void;
    mocks.preview.mockImplementationOnce((_request, callbacks) => { latestSuccess = callbacks.onSuccess; });
    const second = selectPhoto(photo("second.png"));
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(`blob:${first.name}`);
    expect(screen.getByAltText("Selected Group invite image header")).toHaveAttribute("src", "blob:second.png");
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(3));
    act(() => latestSuccess(preview({ message_type: "group_invite" })));
    fireEvent.click(screen.getByRole("button", { name: "Send individually to 2" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledWith(expect.objectContaining({ headerImage: second, headerImageId: null })));
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:second.png");
  });

  it("discards a delayed old preview after photo removal", async () => {
    let oldSuccess!: (value: WhatsAppPreviewResponse) => void;
    mocks.preview.mockImplementationOnce((_request, callbacks) => { oldSuccess = callbacks.onSuccess; });
    mount();
    selectPhoto();
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Remove photo" }));
    act(() => oldSuccess(preview({ message_type: "group_invite" })));
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    await screen.findByDisplayValue(link);
    expect(screen.getByRole("button", { name: /Send individually/ })).toBeDisabled();
    expect(screen.queryByText("Saved message image")).not.toBeInTheDocument();
  });

  it("requires a replacement for mixed legacy bulk snapshots and keeps per-recipient photo reuse explicit", async () => {
    mocks.bulkPreview.mockImplementation(({ overrides, recipientIds }, callbacks) => callbacks.onSuccess({
      ...preview({ message_type: "group_invite", message_content: overrides.messageContent, group_invite_link: overrides.groupInviteLink }),
      selected: recipientIds.length, eligible_recipient_ids: recipientIds, skipped_no_saved_message: 0, skipped_replaced: 0, skipped_ineligible: 0, skipped_in_progress: 0, skipped_delivery_unknown: 0, missing_header_image_count: 1,
    }));
    const { onSend } = mount({ bulkRecipients: mocks.detail.recipients });
    await screen.findByText("1 selected recipient has no saved invitation photo. Choose a replacement photo before resending.");
    expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeDisabled();
    const image = selectPhoto();
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeEnabled());
    expect(mocks.bulkPreview).toHaveBeenLastCalledWith(expect.objectContaining({ overrides: { messageContent: null, groupInviteLink: null, headerImageId: null } }), expect.any(Object));
    fireEvent.click(screen.getByRole("button", { name: "Resend to 2 selected" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledWith(expect.objectContaining({ headerImage: image, headerImageId: null, bulkDraft: { messageContent: null, groupInviteLink: null, headerImageId: null } })));
    fireEvent.click(screen.getByRole("button", { name: "Use each recipient’s saved photo" }));
    await waitFor(() => expect(mocks.bulkPreview).toHaveBeenCalledTimes(3));
    expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeDisabled();
  });

  it("keeps the selected photo after upload failure and invalidates bulk recovery when the photo changes", async () => {
    const onSend = vi.fn().mockRejectedValueOnce(new Error("Photo upload failed. Try again.")).mockResolvedValue(undefined);
    mount({ bulkRecipients: mocks.detail.recipients, onSend });
    await screen.findByDisplayValue(link);
    selectPhoto();
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Resend to 2 selected" }));
    await screen.findByRole("button", { name: "Check resend status" });
    expect(screen.getByRole("alert")).toHaveTextContent("Photo upload failed. Try again.");
    expect(screen.getByAltText("Selected Group invite image header")).toHaveAttribute("src", "blob:invitation.png");
    const replacement = selectPhoto(photo("replacement.png"));
    expect(screen.queryByRole("button", { name: "Check resend status" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Resend to 2 selected" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Resend to 2 selected" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    expect(onSend).toHaveBeenLastCalledWith(expect.objectContaining({ headerImage: replacement }));
  });
});
