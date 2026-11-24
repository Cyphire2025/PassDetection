"use client";
import { useTravellerDocumentPreview } from "../hooks/use-traveller-document-preview";
import { TravellerDocumentContent, type TravellerDocumentProps } from "./traveller-document-content";

export function TravellerDocument({ id, label, draftId, temporary = false, available = true }: TravellerDocumentProps) {
  const preview = useTravellerDocumentPreview(id, draftId, temporary, available);
  return <TravellerDocumentContent label={label} temporary={temporary} available={available} {...preview} />;
}
