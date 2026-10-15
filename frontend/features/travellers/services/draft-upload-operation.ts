import type { DraftSide, ReturningDraft } from "../api/returning-draft.api";
import { draftFileIdentity } from "./draft-file-identity";

type UploadView = Pick<ReturningDraft, "id" | "revision" | "status" | "documents">;
export interface DraftUploadOperation { side: DraftSide; fingerprint: string; revision: number; key: string; assetId: string | null; draftId: string }
const sideId = (view: UploadView, side: DraftSide) => view.documents.find((document) => document.side === side)?.id ?? null;
export const isDraftConflict = (cause: unknown) => !!cause && typeof cause === "object" && "status" in cause && cause.status === 409;

export async function prepareDraftUpload(previous: DraftUploadOperation | null, side: DraftSide, file: File, view: UploadView): Promise<DraftUploadOperation> {
  const fingerprint = await draftFileIdentity(file);
  if (previous?.side === side && previous.fingerprint === fingerprint && previous.draftId === view.id) return previous;
  return { side, fingerprint, revision: view.revision, key: crypto.randomUUID(), assetId: sideId(view, side), draftId: view.id };
}

/** Retry at most once, only if no other upload replaced the requested side. */
export async function sendDraftUpload<T extends UploadView>(request: DraftUploadOperation, send: (request: DraftUploadOperation) => Promise<T>, read: () => Promise<T>, replace: (request: DraftUploadOperation | null) => void, receive: (view: T) => void, signal: AbortSignal): Promise<T> {
  try { return await send(request); }
  catch (cause) {
    if (!isDraftConflict(cause) || signal.aborted) throw cause;
    replace(null);
    const remote = await read();
    signal.throwIfAborted();
    if (remote.id !== request.draftId || remote.status !== "active") throw cause;
    if (sideId(remote, request.side) !== request.assetId || remote.revision <= request.revision) {
      receive(remote);
      throw new Error("This image changed in another window. Review the latest image before replacing it.");
    }
    const retry = { ...request, revision: remote.revision, key: crypto.randomUUID() };
    replace(retry);
    return send(retry);
  }
}
