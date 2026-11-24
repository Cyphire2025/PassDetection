import { assertRequestOwner, RequestOwnerChangedError } from "@/lib/api/request-owner";
import { notificationsApi } from "./notifications.api";
import type { NotificationDraft, NotificationDraftInput, NotificationSendInput } from "./notification-types";

/** One staff action owns every HTTP continuation and its eventual recovery/cache effects. */
export function notificationOperation(agencyId: string, actorId: string, isActive: () => boolean) {
  const assertCurrent = () => {
    if (!isActive()) throw new RequestOwnerChangedError();
    assertRequestOwner({ expectedOwnerUserId: actorId });
  };
  const checked = async <T>(request: () => Promise<T>): Promise<T> => {
    assertCurrent();
    try {
      const result = await request();
      assertCurrent();
      return result;
    } catch (error) {
      assertCurrent();
      throw error;
    }
  };
  return {
    assertCurrent,
    createDraft: (body: NotificationDraftInput) => checked(() => notificationsApi.createDraft(agencyId, body, actorId)),
    updateDraft: (draft: NotificationDraft, body: NotificationDraftInput) => checked(() => notificationsApi.updateDraft(agencyId, draft, body, actorId)),
    preview: (draft: NotificationDraft) => checked(() => notificationsApi.preview(agencyId, draft, actorId)),
    send: (draftId: string, body: NotificationSendInput) => checked(() => notificationsApi.send(agencyId, draftId, body, actorId)),
    byRequest: (requestId: string, draftId: string) => checked(() => notificationsApi.byRequest(agencyId, requestId, draftId, actorId)),
    getDraft: (draftId: string) => checked(() => notificationsApi.getDraft(agencyId, draftId, actorId)),
  };
}

export type NotificationOperation = ReturnType<typeof notificationOperation>;
