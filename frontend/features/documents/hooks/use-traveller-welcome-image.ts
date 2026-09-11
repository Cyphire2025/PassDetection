import { useEffect, useRef, useState } from "react";
import { whatsappApi } from "@/features/whatsapp/api/whatsapp.api";

interface WelcomeImage {
  sourceId: string;
  mediaId: string;
  previewUrl: string;
}

export function useTravellerWelcomeImage() {
  const [image, setImage] = useState<WelcomeImage | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const uploadInFlight = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => () => { if (image?.previewUrl) URL.revokeObjectURL(image.previewUrl); }, [image?.previewUrl]);

  const upload = async (sourceId: string, file: File) => {
    if (uploadInFlight.current) return;
    if (!["image/jpeg", "image/png"].includes(file.type) || file.size > 5 * 1024 * 1024 || file.size === 0) {
      setError("Choose a JPG or PNG image up to 5 MB.");
      return;
    }
    uploadInFlight.current = true;
    setUploading(true);
    setError(null);
    try {
      const result = await whatsappApi.uploadWelcomeImage(sourceId, file);
      if (mounted.current) setImage({ sourceId, mediaId: result.media_id, previewUrl: URL.createObjectURL(file) });
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : "The welcome image could not be uploaded. Try again.");
    } finally {
      uploadInFlight.current = false;
      if (mounted.current) setUploading(false);
    }
  };
  return { image, uploading, error, upload, clear: () => { setImage(null); setError(null); } };
}
