const MAX_GALLERY_SCROLL_ANCHORS = 32;

export type GalleryScrollAnchor = Readonly<{
  assetId: string;
  absoluteIndex: number;
}>;

const anchors = new Map<string, GalleryScrollAnchor>();

export function rememberGalleryScrollAnchor(
  boundary: string,
  anchor: GalleryScrollAnchor,
): void {
  if (!boundary || !anchor.assetId || !Number.isSafeInteger(anchor.absoluteIndex) || anchor.absoluteIndex < 0) {
    return;
  }
  anchors.delete(boundary);
  anchors.set(boundary, Object.freeze(anchor));
  while (anchors.size > MAX_GALLERY_SCROLL_ANCHORS) {
    const oldest = anchors.keys().next().value as string | undefined;
    if (!oldest) break;
    anchors.delete(oldest);
  }
}

export function readGalleryScrollAnchor(boundary: string): GalleryScrollAnchor | null {
  const anchor = anchors.get(boundary);
  if (!anchor) return null;
  anchors.delete(boundary);
  anchors.set(boundary, anchor);
  return anchor;
}

export function clearGalleryScrollAnchors(): void {
  anchors.clear();
}
