export const NORMAL_SEND_STORAGE_PREFIX = "passdetection:whatsapp-send:v1:";

export interface NormalSendRecord {
  version: 1;
  key: string;
  draftHash: string;
  mediaId: string | null;
  payloadHash: string | null;
  state: "pending" | "acknowledged" | "superseded";
}

export class UncertainWhatsAppSendError extends Error {
  constructor(readonly startNew: () => void) {
    super("An earlier send has not been confirmed and this draft differs. Restore the same text, audience and photo to retry it, or check delivery history before starting a new send.");
    this.name = "UncertainWhatsAppSendError";
  }
}

export async function sendFingerprint(value: string | ArrayBuffer): Promise<string> {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function imageFingerprint(image: File | null | undefined): Promise<string | null> {
  if (!image) return null;
  if (image.size > 5 * 1024 * 1024) throw new Error("The message image must be 5 MB or smaller.");
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("The selected photo could not be read. Choose it again."));
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.readAsArrayBuffer(image);
  });
  return sendFingerprint(JSON.stringify([image.name, image.type, await sendFingerprint(bytes)]));
}

export function readSendRecord(storageKey: string): NormalSendRecord | null {
  let raw: string | null;
  try { raw = window.sessionStorage.getItem(storageKey); }
  catch { throw new Error("Safe send recovery needs session storage. Allow it before sending."); }
  if (raw === null) return null;
  try {
    const item = JSON.parse(raw) as Partial<NormalSendRecord> | null;
    if (item?.version === 1 && typeof item.key === "string" && /^[\x21-\x7e]{16,256}$/.test(item.key)
      && typeof item.draftHash === "string" && /^[a-f0-9]{64}$/.test(item.draftHash)
      && (item.mediaId === null || (typeof item.mediaId === "string" && item.mediaId.length <= 512))
      && (item.payloadHash === null || (typeof item.payloadHash === "string" && /^[a-f0-9]{64}$/.test(item.payloadHash)))
      && ["pending", "acknowledged", "superseded"].includes(item.state ?? "")) return item as NormalSendRecord;
  } catch { /* Unknown state must not silently become another send. */ }
  throw new Error("The previous send recovery record cannot be read. Check delivery history before clearing this tab's session data or starting another send.");
}

export function writeSendRecord(storageKey: string, record: NormalSendRecord, expectedKey?: string) {
  if (expectedKey !== undefined && readSendRecord(storageKey)?.key !== expectedKey) {
    throw new Error("The send session changed. Reopen the broadcast before continuing.");
  }
  try { window.sessionStorage.setItem(storageKey, JSON.stringify(record)); }
  catch { throw new Error("The send recovery record could not be saved. Allow session storage before sending."); }
}
