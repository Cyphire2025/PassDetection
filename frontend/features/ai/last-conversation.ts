const PREFIX = "gc:ai:last-conversation:v1:";
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

/** Only an opaque conversation ID is stored; transcripts always come from the authenticated API. */
export function rememberedConversation(owner: string | null): string | null {
  if (!owner) return null;
  try {
    const id = localStorage.getItem(PREFIX + owner);
    return id && UUID.test(id) ? id : null;
  } catch { return null; }
}

export function rememberConversation(owner: string | null, id: string | null) {
  if (!owner) return;
  try { localStorage.setItem(PREFIX + owner, id ?? "new"); }
  catch { /* Private browsing or full storage must not prevent a conversation. */ }
}
