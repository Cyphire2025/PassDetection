/** Identity for one reviewed send, including its resolved header media. */
export class WhatsAppSendIntent {
  readonly key: string;
  private payload: string | null = null;
  private media: Promise<string> | null;

  constructor(
    key: string = crypto.randomUUID(),
    mediaId: string | null = null,
    private readonly retainMedia: (mediaId: string) => void = () => undefined,
    private readonly retainPayload: (signature: string) => Promise<void> = async () => undefined,
  ) {
    if (!/^[\x21-\x7e]{16,256}$/.test(key)) throw new Error("A valid send request identity is required.");
    this.key = key;
    this.media = mediaId === null ? null : Promise.resolve(mediaId);
  }

  async bind(groupId: string, payload: unknown) {
    const signature = JSON.stringify([groupId, payload]);
    if (this.payload !== null && this.payload !== signature) {
      throw new Error("The reviewed send changed. Review it again before starting a new send.");
    }
    await this.retainPayload(signature);
    this.payload = signature;
  }

  resolveImage(upload: () => Promise<string>): Promise<string> {
    // Retain the resolved ID before sending. A retry must not change the
    // server's exact-payload fingerprint by uploading the same image again.
    if (!this.media) {
      this.media = upload().then((mediaId) => {
        this.retainMedia(mediaId);
        return mediaId;
      }).catch((error) => {
        this.media = null; // No send occurred until the media upload resolved.
        throw error;
      });
    }
    return this.media;
  }
}
