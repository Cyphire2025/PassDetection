"use client";

import { useState } from "react";
import { ImagePlus, Wallpaper } from "lucide-react";
import { Button } from "@/components/ui/button";
import { GroupImageDialog } from "./group-image-dialog";

type GroupImages = { group_id: string; banner_url?: string | null; background_url?: string | null };

export function GroupBannerAction({ group, disabled }: { group?: GroupImages | null; disabled: boolean }) {
  const [editor, setEditor] = useState<"banner" | "background" | null>(null);
  if (!group || disabled) return null;
  // The temporary first-image frame includes its post-save toolbar dimensions.
  const bannerLabel = group.banner_url || editor === "banner" ? "Edit banner" : "Add banner";
  return <>
    <Button type="button" variant="secondary" size="sm" aria-label={bannerLabel} title={bannerLabel} onClick={() => setEditor("banner")}>
      <ImagePlus className="h-4 w-4" aria-hidden="true" /><span className="hidden sm:inline">{bannerLabel}</span>
    </Button>
    <Button type="button" variant="secondary" size="sm" aria-label="Edit background" title="Edit background" onClick={() => setEditor("background")}>
      <Wallpaper className="h-4 w-4" aria-hidden="true" /><span className="hidden sm:inline">Edit background</span>
    </Button>
    {editor && <GroupImageDialog key={editor} kind={editor} groupId={group.group_id}
      currentUrl={editor === "banner" ? group.banner_url : group.background_url} onClose={() => setEditor(null)} />}
  </>;
}
