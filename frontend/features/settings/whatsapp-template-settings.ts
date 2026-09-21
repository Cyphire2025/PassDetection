export type WhatsAppTemplateKey =
  | "welcome"
  | "passport_link"
  | "reminder"
  | "group_invite"
  | "document"
  | "qr"
  | "otp";

export interface WhatsAppTemplateSetting {
  key: WhatsAppTemplateKey;
  label: string;
  environment_name: string;
  override_name: string | null;
  effective_name: string;
  language: string;
  source: "environment" | "override";
  contract_description: string;
}

export interface WhatsAppTemplateSettings {
  revision: number;
  can_edit: boolean;
  updated_at: string | null;
  templates: WhatsAppTemplateSetting[];
}

export type WhatsAppTemplateOverrides = Partial<
  Record<WhatsAppTemplateKey, string | null>
>;

export const WHATSAPP_TEMPLATE_NAME_MAX_LENGTH = 255;

export function templateNameError(value: string | null): string | null {
  if (value === null) return null;
  if (!value) return "Enter a template name, or use the environment default.";
  if (value.length > WHATSAPP_TEMPLATE_NAME_MAX_LENGTH) {
    return "Use a template name with no more than 255 characters.";
  }
  if (!/^[a-z0-9_]+$/.test(value)) {
    return "Use only lowercase letters, numbers and underscores.";
  }
  return null;
}
