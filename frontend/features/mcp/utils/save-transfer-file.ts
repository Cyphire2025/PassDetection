type SaveHandle = { createWritable(): Promise<{ write(blob: Blob): Promise<void>; close(): Promise<void>; abort?(): Promise<void> }> };
type SaveWindow = Window & { showSaveFilePicker?: (options: { suggestedName: string; types: { description: string; accept: Record<string, string[]> }[] }) => Promise<SaveHandle> };

/** Only a completed filesystem write is detectable. Anchor downloads need user confirmation. */
export async function saveTransferFile(blob: Blob, filename: string, mediaType: string): Promise<"saved" | "confirm"> {
  const browser = window as SaveWindow;
  if (browser.showSaveFilePicker) {
    const handle = await browser.showSaveFilePicker({ suggestedName: filename,
      types: [{ description: "Prepared Global Connects file", accept: { [mediaType]: [`.${filename.split(".").at(-1)}`] } }] });
    const writable = await handle.createWritable();
    try { await writable.write(blob); await writable.close(); }
    catch (error) { await writable.abort?.().catch(() => undefined); throw error; }
    return "saved";
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.rel = "noopener";
  document.body.append(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  return "confirm";
}
