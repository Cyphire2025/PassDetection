export function validWhatsAppGroupInviteLink(value: string): boolean {
  try {
    const raw = value.trim();
    if (/\s/.test(raw) || Array.from(raw).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127) || !raw.startsWith("https://chat.whatsapp.com/")) return false;
    const url = new URL(raw);
    return url.protocol === "https:" && url.hostname === "chat.whatsapp.com"
      && !url.username && !url.password && !url.port && !url.hash
      && /^\/[A-Za-z0-9]+\/?$/.test(url.pathname);
  } catch {
    return false;
  }
}

export const GROUP_INVITE_LINK_HELP = "Paste the official WhatsApp group invite link beginning with https://chat.whatsapp.com/.";
