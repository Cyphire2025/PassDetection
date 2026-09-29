import { WhatsAppSendIntent } from "./normal-send-intent";
import {
  imageFingerprint, NORMAL_SEND_STORAGE_PREFIX, readSendRecord, sendFingerprint,
  UncertainWhatsAppSendError, writeSendRecord, type NormalSendRecord,
} from "./normal-send-storage";

type SendVariables = { groupId: string; image?: File | null; recipientIds: string[] | null };

/** Durable within one tab; the existing auth cleanup removes all owned keys. */
export class NormalWhatsAppSendController<Result> {
  private readonly inFlight = new Map<string, Promise<Result>>();
  private readonly preparing = new Map<string, { image: File | null; operation: Promise<Result> }>();

  run<Variables extends SendVariables>(
    scope: string,
    mode: string,
    variables: Variables,
    send: (variables: Variables, intent: WhatsAppSendIntent) => Promise<Result>,
    assertCurrentActor: () => void,
  ): Promise<Result> {
    const reviewed = {
      ...Object.fromEntries(Object.entries(variables).map(([key, value]) =>
        [key, Array.isArray(value) ? [...value] : value])),
      recipientIds: variables.recipientIds === null ? null : [...variables.recipientIds].sort(),
    } as Variables;
    const draft = JSON.stringify(Object.entries(reviewed).filter(([key]) => key !== "image")
      .sort(([left], [right]) => left.localeCompare(right)));
    const preparationKey = JSON.stringify([scope, mode, draft]);
    const image = variables.image ?? null;
    const existing = this.preparing.get(preparationKey);
    if (existing?.image === image) return existing.operation;
    const operation = this.prepare(scope, mode, reviewed, draft, send, assertCurrentActor).finally(() => {
      if (this.preparing.get(preparationKey)?.operation === operation) this.preparing.delete(preparationKey);
    });
    this.preparing.set(preparationKey, { image, operation });
    return operation;
  }

  private async prepare<Variables extends SendVariables>(
    scope: string, mode: string, reviewed: Variables, draft: string,
    send: (variables: Variables, intent: WhatsAppSendIntent) => Promise<Result>,
    assertCurrentActor: () => void,
  ): Promise<Result> {
    const [scopeHash, fileHash] = await Promise.all([
      sendFingerprint(JSON.stringify([scope, mode, reviewed.groupId])), imageFingerprint(reviewed.image),
    ]);
    const storageKey = NORMAL_SEND_STORAGE_PREFIX + scopeHash;
    const draftHash = await sendFingerprint(JSON.stringify([draft, fileHash]));
    assertCurrentActor();
    let record = readSendRecord(storageKey);
    if (record && record.state === "pending" && record.draftHash !== draftHash) {
      const retained = record;
      throw new UncertainWhatsAppSendError(() => {
        assertCurrentActor();
        writeSendRecord(storageKey, { ...retained, state: "superseded" }, retained.key);
      });
    }
    if (!record || record.state !== "pending") {
      record = { version: 1, key: crypto.randomUUID(), draftHash, mediaId: null, payloadHash: null, state: "pending" };
      writeSendRecord(storageKey, record);
    }
    const current = record;
    const existing = this.inFlight.get(current.key);
    if (existing) return existing;
    const operation = this.submit(storageKey, current, reviewed, send, assertCurrentActor)
      .finally(() => { this.inFlight.delete(current.key); });
    this.inFlight.set(current.key, operation);
    return operation;
  }

  private async submit<Variables extends SendVariables>(
    storageKey: string, record: NormalSendRecord, reviewed: Variables,
    send: (variables: Variables, intent: WhatsAppSendIntent) => Promise<Result>,
    assertCurrentActor: () => void,
  ): Promise<Result> {
    const persist = () => {
      assertCurrentActor();
      writeSendRecord(storageKey, record, record.key);
    };
    const intent = new WhatsAppSendIntent(record.key, record.mediaId,
      (mediaId) => { record.mediaId = mediaId; persist(); },
      async (signature) => {
        const payloadHash = await sendFingerprint(signature);
        if (record.payloadHash !== null && record.payloadHash !== payloadHash) {
          throw new Error("The retained send body changed. Check delivery history before starting a different send.");
        }
        record.payloadHash = payloadHash;
        persist();
      });
    const result = await send(reviewed, intent);
    record.state = "acknowledged";
    // A failed acknowledgement write leaves a safely replayable request. It
    // must not turn a known server receipt into a misleading send failure.
    try { persist(); } catch { /* Next attempt can only replay the retained key. */ }
    return result;
  }
}
