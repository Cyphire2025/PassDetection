import { useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth.store";
import type { WhatsAppSendResponse } from "../api/whatsapp.api";
import type { WhatsAppSendIntent } from "../utils/normal-send-intent";
import { NormalWhatsAppSendController } from "../utils/normal-send-controller";

/** Retain only opaque identity and fingerprints across same-tab remounts. */
export function useNormalWhatsAppSend<Variables extends { groupId: string; image?: File | null; recipientIds: string[] | null }>(
  mode: string,
  send: (variables: Variables, intent: WhatsAppSendIntent) => Promise<WhatsAppSendResponse>,
) {
  const controller = useRef(new NormalWhatsAppSendController<WhatsAppSendResponse>());
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (variables: Variables) => {
      const user = useAuthStore.getState().user;
      const scope = JSON.stringify([user?.id ?? null, user?.agency_id ?? null]);
      return controller.current.run(scope, mode, variables, send, () => {
        const current = useAuthStore.getState().user;
        if (!current || JSON.stringify([current.id, current.agency_id]) !== scope) {
          throw new Error("Your account changed. Reopen the broadcast before sending.");
        }
      });
    },
    retry: false,
    onSuccess: async () => {
      // A failed cache refresh must not turn an acknowledged send into a send
      // error that encourages another submission. Queries retain their errors.
      await queryClient.invalidateQueries({ queryKey: ["whatsapp", "groups"] }).catch(() => undefined);
    },
  });
}
