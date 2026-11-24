"use client";

import { useEffect, useRef, useState } from "react";

export function useComposerHeaderImage() {
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const imageUrl = useRef<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  useEffect(
    () => () => {
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    },
    [],
  );
  const selectImage = (file: File) => {
    if (
      !["image/jpeg", "image/png"].includes(file.type) ||
      file.size > 5 * 1024 * 1024
    ) {
      setImageError("Choose a JPEG or PNG image, 5 MB or smaller.");
      return;
    }
    if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    imageUrl.current = URL.createObjectURL(file);
    setImagePreview(imageUrl.current);
    setImage(file);
    setImageError(null);
  };
  return { image, imagePreview, imageError, selectImage };
}
