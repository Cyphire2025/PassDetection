"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ImageIcon, Upload } from "lucide-react";
import Image from "next/image";
import { MessageComposerSection } from "./whatsapp-message-composer-ui";

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = new Set(["image/jpeg", "image/png"]);

export function useGroupInviteImage(savedImageId: string | null) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [mode, setMode] = useState<"saved" | "selected" | "removed">("saved");
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const objectUrl = useRef<string | null>(null);

  useEffect(() => () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
  }, []);

  const replace = (nextFile: File | null, nextMode: typeof mode) => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = nextFile ? URL.createObjectURL(nextFile) : null;
    setFile(nextFile);
    setPreviewUrl(objectUrl.current);
    setMode(nextMode);
    setRevision((current) => current + 1);
  };
  const select = (nextFile: File) => {
    const reason = !IMAGE_TYPES.has(nextFile.type) ? "Use a JPEG or PNG photo."
      : nextFile.size > MAX_IMAGE_BYTES ? "The photo must be 5 MB or smaller." : null;
    setError(reason);
    replace(reason ? null : nextFile, reason ? "removed" : "selected");
  };
  const remove = () => { setError(null); replace(null, "removed"); };
  const useSaved = () => { setError(null); replace(null, "saved"); };
  const imageId = mode === "saved" ? savedImageId : null;
  return { file, previewUrl, imageId, mode, revision, error, hasImage: Boolean(file || imageId), select, remove, useSaved };
}

export function GroupInvitePhotoPicker({ image, savedImageId, bulkMode }: {
  image: ReturnType<typeof useGroupInviteImage>;
  savedImageId: string | null;
  bulkMode: boolean;
}) {
  const inputId = useId();
  return <MessageComposerSection title="Invitation photo" description="This photo appears above the invitation in each private WhatsApp message.">
    <div className="space-y-3">
      <label htmlFor={inputId} className="flex cursor-pointer items-center gap-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 transition hover:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500">
        {image.previewUrl ? <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-white"><Image src={image.previewUrl} alt="Selected invitation photo" fill unoptimized className="object-contain" /></div>
          : <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-white text-slate-500">{image.imageId ? <ImageIcon className="h-6 w-6" aria-hidden="true" /> : <Upload className="h-6 w-6" aria-hidden="true" />}</span>}
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-slate-800">{image.hasImage ? "Replace photo" : "Choose photo"}</span>
          <span className="mt-1 block break-words text-xs leading-5 text-slate-500">{image.file?.name ?? (image.imageId ? bulkMode ? "Each recipient’s saved photo will be reused." : "The saved invitation photo will be reused." : "Choose a JPEG or PNG, up to 5 MB.")}</span>
        </span>
        <input id={inputId} type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" aria-label="Group invite photo" aria-describedby={`${inputId}-hint${image.error ? ` ${inputId}-error` : ""}`} aria-invalid={Boolean(image.error)} required={!image.hasImage} className="sr-only" onChange={(event) => {
          const selected = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (selected) image.select(selected);
        }} />
      </label>
      <p id={`${inputId}-hint`} className="text-xs leading-5 text-slate-500">A photo is required before sending. Your selected photo is uploaded when you send.</p>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {image.hasImage && <button type="button" onClick={image.remove} className="text-xs font-semibold text-slate-600 underline">Remove photo</button>}
        {savedImageId && image.mode !== "saved" && <button type="button" onClick={image.useSaved} className="text-xs font-semibold text-blue-700 underline">{bulkMode ? "Use each recipient’s saved photo" : "Use saved photo"}</button>}
      </div>
      {image.error && <p id={`${inputId}-error`} role="alert" className="text-sm text-red-700">{image.error}</p>}
    </div>
  </MessageComposerSection>;
}
