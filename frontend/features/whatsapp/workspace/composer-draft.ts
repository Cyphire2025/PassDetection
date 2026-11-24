import type { WhatsAppBroadcastGroupDetail, WhatsAppMessageDraft } from "../api/whatsapp.api";
import type { MessageDefinition } from "./composer.api";
import type { ComposerState } from "./message-composer-state";

/** Resolve the original selection and linked-group rules into a preview draft. */
export function resolveComposerDraft(
  definition: MessageDefinition,
  group: WhatsAppBroadcastGroupDetail,
  state: ComposerState,
  eligible: WhatsAppBroadcastGroupDetail["recipients"],
) {
  const activeLinks =
    group.linked_client_groups?.filter((item) => item.status === "active") ??
    [];
  const reminderGroupId =
    state.reminderGroupId ??
    (activeLinks.length === 1 ? activeLinks[0].id : null);
  const audienceReady =
    state.reminderAudience !== "not_submitted" || Boolean(reminderGroupId);
  const selectedIds =
    state.recipientIds ?? eligible.map((recipient) => recipient.id);
  const selectedIdSet = new Set(selectedIds);
  const draft: WhatsAppMessageDraft = {
    message_type: definition.message_type,
    ...state.fields,
    ...(definition.message_type === "passport_link"
      ? { include_previous_recipients: state.includePreviousRecipients }
      : {}),
    recipient_ids: selectedIds.length
      ? selectedIds
      : eligible.map((recipient) => recipient.id),
    recipient_id:
      state.previewRecipientId && selectedIdSet.has(state.previewRecipientId)
        ? state.previewRecipientId
        : null,
    support_contact_ids:
      definition.message_type === "passport_link" && state.supportContactId
        ? [state.supportContactId]
        : null,
    ...(definition.audience === "reminder"
      ? {
        audience: state.reminderAudience,
        audience_client_group_id:
          state.reminderAudience === "not_submitted" ? reminderGroupId : null,
      }
      : {}),
    ...(definition.audience === "update"
      ? {
        update_submission: state.submission,
        update_distribution: state.distribution,
        update_document_type: state.documentType,
      }
      : {}),
  };
  return { activeLinks, reminderGroupId, audienceReady, selectedIds, selectedIdSet, draft };
}
