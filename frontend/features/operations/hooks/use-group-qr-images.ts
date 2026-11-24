import { useEffect, useState } from "react";
import { createQrImageGenerator, planQrImageGeneration, type CachedQrImage } from "../services/qr-image-generation";
import type { Dispatch, SetStateAction } from "react";
import type { QrImageMap } from "../components/group-qr-model";
import { INITIAL_QR_CARD_LIMIT } from "../components/group-qr-model";

export function useGroupQrImages({
  visiblePayloads,
  printRequested,
  setPrintRequested,
  setRenderLimit,
  setActionError,
}: {
  visiblePayloads: Record<string, string>;
  printRequested: boolean;
  setPrintRequested: Dispatch<SetStateAction<boolean>>;
  setRenderLimit: Dispatch<SetStateAction<number>>;
  setActionError: Dispatch<SetStateAction<string | null>>;
}) {
  const [qrImages, setQrImages] = useState<QrImageMap>({});
  const [qrGenerationFailureCount, setQrGenerationFailureCount] = useState(0);
  const [qrImageCache] = useState(
    () => new Map<string, CachedQrImage>(),
  );
  const [qrImageGenerator] = useState(() => createQrImageGenerator());

  useEffect(() => {
    const controller = new AbortController();
    let animationFrameId: number | null = null;
    let pendingImages: QrImageMap = {};

    const flushPendingImages = () => {
      animationFrameId = null;
      if (controller.signal.aborted || Object.keys(pendingImages).length === 0) {
        pendingImages = {};
        return;
      }
      const nextImages = pendingImages;
      pendingImages = {};
      setQrImages((current) => ({ ...current, ...nextImages }));
    };

    async function generateQrImages() {
      const revealed = Object.entries(visiblePayloads);
      const visiblePassengerIds = new Set(revealed.map(([passengerId]) => passengerId));
      for (const [passengerId, cached] of qrImageCache) {
        if (
          !visiblePassengerIds.has(passengerId)
          || visiblePayloads[passengerId] !== cached.payload
        ) {
          qrImageCache.delete(passengerId);
        }
      }

      if (revealed.length === 0) {
        setQrImages({});
        setQrGenerationFailureCount(0);
        return;
      }

      const { cachedEntries, pendingEntries } = planQrImageGeneration(
        revealed,
        qrImageCache,
      );
      setQrImages(Object.fromEntries(cachedEntries));
      setQrGenerationFailureCount(0);
      if (pendingEntries.length === 0) return;

      const result = await qrImageGenerator.generate(pendingEntries, {
        signal: controller.signal,
        onEntry: ([passengerId, imageUrl]) => {
          const payload = visiblePayloads[passengerId];
          if (!payload || controller.signal.aborted) return;
          qrImageCache.set(passengerId, { payload, imageUrl });
          pendingImages[passengerId] = imageUrl;
          animationFrameId ??= window.requestAnimationFrame(flushPendingImages);
        },
      });

      if (!controller.signal.aborted) {
        if (animationFrameId !== null) {
          window.cancelAnimationFrame(animationFrameId);
          flushPendingImages();
        }
        setQrGenerationFailureCount(result.failedPassengerIds.length);
        if (printRequested && result.failedPassengerIds.length > 0) {
          setPrintRequested(false);
          setActionError("The print sheet could not be prepared because one or more QR images failed to render. Refresh and try again.");
        }
      }
    }

    void generateQrImages().catch(() => {
      if (!controller.signal.aborted) {
        setQrGenerationFailureCount(1);
        if (printRequested) {
          setPrintRequested(false);
          setActionError("The print sheet could not be prepared because QR images failed to render. Refresh and try again.");
        }
      }
    });
    return () => {
      controller.abort();
      if (animationFrameId !== null) {
        window.cancelAnimationFrame(animationFrameId);
      }
    };
  }, [printRequested, qrImageCache, qrImageGenerator, visiblePayloads, setPrintRequested, setActionError]);

  useEffect(() => {
    if (!printRequested) return;
    const payloadPassengerIds = Object.keys(visiblePayloads);
    const allImagesReady = payloadPassengerIds.every((passengerId) => Boolean(qrImages[passengerId]));
    if (!allImagesReady || qrGenerationFailureCount > 0) return;
    const frame = window.requestAnimationFrame(() => {
      window.print();
      setPrintRequested(false);
      setRenderLimit(INITIAL_QR_CARD_LIMIT);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [printRequested, qrGenerationFailureCount, qrImages, visiblePayloads, setPrintRequested, setRenderLimit]);

  return { qrImages, qrGenerationFailureCount };
}
