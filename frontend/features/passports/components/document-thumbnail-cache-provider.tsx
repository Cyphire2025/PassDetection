"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { DocumentThumbnailCache } from "../services/document-thumbnail-cache";

const DocumentThumbnailCacheContext = createContext<DocumentThumbnailCache | null>(null);

export function DocumentThumbnailCacheProvider({ children }: { children: ReactNode }) {
  const [cache] = useState(() => new DocumentThumbnailCache());
  useEffect(() => () => cache.clear(), [cache]);
  return (
    <DocumentThumbnailCacheContext.Provider value={cache}>
      {children}
    </DocumentThumbnailCacheContext.Provider>
  );
}

export function useDocumentThumbnailCache() {
  return useContext(DocumentThumbnailCacheContext);
}
