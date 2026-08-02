export const QR_IMAGE_GENERATION_CONCURRENCY = 4;

export type QrPayloadEntry = readonly [passengerId: string, payload: string];
export type QrImageEntry = readonly [passengerId: string, imageUrl: string];

export interface CachedQrImage {
  payload: string;
  imageUrl: string;
}

type QrPayloadRenderer = (payload: string) => Promise<string>;

interface CreateQrImageGeneratorOptions {
  concurrency?: number;
  renderPayload?: QrPayloadRenderer;
}

interface GenerateQrImageEntriesOptions {
  onEntry?: (entry: QrImageEntry) => void;
  signal?: AbortSignal;
}

export interface QrImageGenerationResult {
  entries: QrImageEntry[];
  failedPassengerIds: string[];
}

interface QueuedRender {
  passengerId: string;
  payload: string;
  resolve: (entry: QrImageEntry | undefined) => void;
  reject: (error: unknown) => void;
  signal?: AbortSignal;
}

let qrCodeModulePromise: Promise<typeof import("qrcode")> | null = null;

async function renderQrPayload(payload: string): Promise<string> {
  qrCodeModulePromise ??= import("qrcode").catch((error) => {
    qrCodeModulePromise = null;
    throw error;
  });
  const QRCode = await qrCodeModulePromise;
  return QRCode.toDataURL(payload, {
    errorCorrectionLevel: "M",
    margin: 2,
    scale: 7,
    color: {
      dark: "#020617",
      light: "#ffffff",
    },
  });
}

export function planQrImageGeneration(
  entries: readonly QrPayloadEntry[],
  cache: ReadonlyMap<string, CachedQrImage>,
): {
  cachedEntries: QrImageEntry[];
  pendingEntries: QrPayloadEntry[];
} {
  const cachedEntries: QrImageEntry[] = [];
  const pendingEntries: QrPayloadEntry[] = [];
  for (const [passengerId, payload] of entries) {
    const cached = cache.get(passengerId);
    if (cached?.payload === payload) {
      cachedEntries.push([passengerId, cached.imageUrl]);
    } else {
      pendingEntries.push([passengerId, payload]);
    }
  }
  return { cachedEntries, pendingEntries };
}

export function createQrImageGenerator({
  concurrency = QR_IMAGE_GENERATION_CONCURRENCY,
  renderPayload = renderQrPayload,
}: CreateQrImageGeneratorOptions = {}) {
  const workerLimit = Number.isFinite(concurrency)
    ? Math.max(1, Math.floor(concurrency))
    : QR_IMAGE_GENERATION_CONCURRENCY;
  const queue: QueuedRender[] = [];
  let activeWorkers = 0;

  const drain = () => {
    while (activeWorkers < workerLimit && queue.length > 0) {
      const task = queue.shift();
      if (!task) return;
      if (task.signal?.aborted) {
        task.resolve(undefined);
        continue;
      }

      activeWorkers += 1;
      void renderPayload(task.payload)
        .then((imageUrl) => {
          task.resolve(
            task.signal?.aborted
              ? undefined
              : [task.passengerId, imageUrl],
          );
        })
        .catch(task.reject)
        .finally(() => {
          activeWorkers -= 1;
          drain();
        });
    }
  };

  const schedule = (
    [passengerId, payload]: QrPayloadEntry,
    signal?: AbortSignal,
  ) => new Promise<QrImageEntry | undefined>((resolve, reject) => {
    queue.push({ passengerId, payload, resolve, reject, signal });
    drain();
  });

  return {
    async generate(
      entries: readonly QrPayloadEntry[],
      { onEntry, signal }: GenerateQrImageEntriesOptions = {},
    ): Promise<QrImageGenerationResult> {
      if (entries.length === 0 || signal?.aborted) {
        return { entries: [], failedPassengerIds: [] };
      }

      const results = new Array<QrImageEntry | undefined>(entries.length);
      const failedPassengerIds: string[] = [];
      await Promise.all(
        entries.map(async (entry, index) => {
          try {
            const result = await schedule(entry, signal);
            if (!result || signal?.aborted) return;
            results[index] = result;
            onEntry?.(result);
          } catch {
            if (!signal?.aborted) {
              failedPassengerIds.push(entry[0]);
            }
          }
        }),
      );
      return {
        entries: results.filter(
          (entry): entry is QrImageEntry => entry !== undefined,
        ),
        failedPassengerIds,
      };
    },
  };
}

export async function generateQrImageEntries(
  entries: readonly QrPayloadEntry[],
  {
    concurrency = QR_IMAGE_GENERATION_CONCURRENCY,
    renderPayload = renderQrPayload,
    signal,
  }: CreateQrImageGeneratorOptions & { signal?: AbortSignal } = {},
): Promise<QrImageEntry[]> {
  const generator = createQrImageGenerator({ concurrency, renderPayload });
  const result = await generator.generate(entries, { signal });
  return result.entries;
}
