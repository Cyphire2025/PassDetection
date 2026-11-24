import type { WhatsAppPreviewResponse } from "../api/whatsapp.api";
import { validWhatsAppGroupInviteLink } from "../utils/group-invite";
import type { MessageDefinition, MessageField } from "./composer.api";
import type { ComposerState } from "./message-composer-state";

/** Resolve effective field values and the existing template-specific validation. */
export function composerFieldState(
  definition: MessageDefinition,
  state: ComposerState,
  preview: { data: WhatsAppPreviewResponse | undefined },
) {
  const fields = Object.fromEntries(
    definition.fields.map((field) => [
      field.key,
      state.fields[field.key] ?? preview.data?.[field.key] ?? "",
    ]),
  ) as Partial<Record<MessageField["key"], string>>;
  const fieldErrors = Object.fromEntries(
    definition.fields.flatMap((field) => {
      const value = fields[field.key]?.trim() ?? "";
      if (value.length > field.max_length)
        return [[field.key, `Use at most ${field.max_length} characters.`]];
      if (!value || field.kind !== "url") return [];
      if (field.key === "group_invite_link")
        return validWhatsAppGroupInviteLink(value)
          ? []
          : [
            [
              field.key,
              "Paste an official invite beginning with https://chat.whatsapp.com/.",
            ],
          ];
      try {
        const url = new URL(value);
        if (["https:", "http:"].includes(url.protocol)) return [];
      } catch {
        /* display a field-level validation message */
      }
      return [[field.key, "Enter a complete http or https link."]];
    }),
  );
  const fieldReady =
    Object.keys(fieldErrors).length === 0 &&
    definition.fields.every(
      (field) => !field.required || Boolean(fields[field.key]?.trim()),
    );
  return { fields, fieldErrors, fieldReady };
}
