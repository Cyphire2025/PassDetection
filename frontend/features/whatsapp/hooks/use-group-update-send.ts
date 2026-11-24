"use client";

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  groupUpdatesApi,
  type GroupUpdateRequest,
  type GroupUpdateResult,
} from "../api/group-updates.api";
import { whatsappBatchHttpStatus } from "../utils/batch-polling";

/** Retain one reviewed request until its outcome is known. */
export function useGroupUpdateSend(
  groupId: string,
  onSuccess: (result: GroupUpdateResult) => void,
) {
  const submitting = useRef(false);
  const [submittedRequest, setSubmittedRequest] = useState<GroupUpdateRequest | null>(null);
  const send = useMutation({
    mutationFn: (request: GroupUpdateRequest) => groupUpdatesApi.send(groupId, request),
    retry: false,
    onSuccess,
    onError: (error) => {
      if ([400, 403, 404, 409, 422].includes(whatsappBatchHttpStatus(error) ?? 0)) {
        setSubmittedRequest(null);
      }
    },
    onSettled: () => { submitting.current = false; },
  });

  function submit(createRequest: () => GroupUpdateRequest | null) {
    if (submitting.current || send.isSuccess) return;
    const request = submittedRequest ?? createRequest();
    if (!request) return;
    submitting.current = true;
    setSubmittedRequest(request);
    send.mutate(request);
  }

  return { send, submittedRequest, submit };
}
