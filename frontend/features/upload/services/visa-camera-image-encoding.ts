

export function canvasToJpeg(
  canvas: HTMLCanvasElement,
  quality: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (value) => value ? resolve(value) : reject(new Error("Could not save the Visa Photo.")),
      "image/jpeg",
      quality,
    );
  });
}

export async function decodeVisaPhoto(blob: Blob): Promise<{
  image: HTMLImageElement;
  close: () => void;
}> {
  const objectUrl = URL.createObjectURL(blob);
  const image = new window.Image();
  image.decoding = "async";
  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(
        new Error("The captured Visa Photo could not be decoded."),
      );
      image.src = objectUrl;
    });
    return {
      image,
      close: () => URL.revokeObjectURL(objectUrl),
    };
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}
