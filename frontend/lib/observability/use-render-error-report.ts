"use client";

import { useEffect, useState } from "react";
import { reportRenderError, type RenderErrorBoundary } from "./render-errors";

export function useRenderErrorReport(error: unknown, boundary: RenderErrorBoundary) {
  const [reference, setReference] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void reportRenderError(error, boundary).then((eventId) => {
      if (active) setReference(eventId);
    });
    return () => { active = false; };
  }, [error, boundary]);
  return reference;
}
