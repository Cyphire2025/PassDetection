import { useEffect, useRef, useState } from "react";
import { copyTextToClipboard } from "@/lib/utils/clipboard";

export function useUploadLinkCopy() {
  const [copiedLinkKey, setCopiedLinkKey] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const sequence = useRef(0);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearFeedbackTimeout = () => {
    if (timeout.current !== null) clearTimeout(timeout.current);
    timeout.current = null;
  };
  useEffect(() => () => {
    sequence.current++;
    clearFeedbackTimeout();
  }, []);

  const copyUploadLink = async (linkId: string, targetKey: string, url: string) => {
    const operation = ++sequence.current;
    clearFeedbackTimeout();
    try {
      await copyTextToClipboard(url);
      if (operation !== sequence.current) return;
      setCopyError(null);
      setCopiedLinkKey(`${linkId}:${targetKey}`);
      timeout.current = setTimeout(() => {
        timeout.current = null;
        setCopiedLinkKey(null);
      }, 2_000);
    } catch {
      if (operation !== sequence.current) return;
      setCopiedLinkKey(null);
      setCopyError("Could not copy the link. Check your browser clipboard permission and try again.");
    }
  };
  return { copiedLinkKey, copyError, copyUploadLink };
}
