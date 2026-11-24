import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { useAuthStore } from "@/stores/auth.store";
import type { WhatsAppSendResponse } from "../api/whatsapp.api";
import type { WhatsAppSendIntent } from "../utils/normal-send-intent";
import { NormalWhatsAppSendController } from "../utils/normal-send-controller";

/** Retain only opaque identity and fingerprints across same-tab remounts. */
export function useNormalWhatsAppSend<Variables extends { groupId: string; image?: File | null; recipientIds: string[] | null }>(
  mode: string,
  send: (variables: Variables, intent: WhatsAppSendIntent) => Promise<WhatsAppSendResponse>,
) {
  const [controller] = useState(() => new NormalWhatsAppSendController<WhatsAppSendResponse>());
  const queryClient = useQueryClient();
  return usePrivateMutation({
    mutationFn: (variables: Variables, _context, owner) => {
      const user = useAuthStore.getState().user;
      const scope = JSON.stringify([user?.id ?? null, user?.agency_id ?? null]);
      return controller.run(scope, mode, variables, send, owner.assertCurrent);
    },
    retry: false,
    onSuccess: async () => {
      // A failed cache refresh must not turn an acknowledged send into a send
      // error that encourages another submission. Queries retain their errors.
      await queryClient.invalidateQueries({ queryKey: ["whatsapp", "groups"] }).catch(() => undefined);
    },
  });
}
