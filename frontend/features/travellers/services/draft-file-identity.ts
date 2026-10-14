const identities = new WeakMap<File, Promise<string>>();

/** O(file bytes), bounded by upload limits; cache only the digest, never image bytes. */
export function draftFileIdentity(file: File): Promise<string> {
  const existing = identities.get(file);
  if (existing) return existing;
  const identity = new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(new Error("This image could not be read. Choose it again."));
    reader.readAsArrayBuffer(file);
  }).then((bytes) => crypto.subtle.digest("SHA-256", bytes))
    .then((digest) => Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join(""));
  identities.set(file, identity);
  void identity.catch(() => identities.delete(file));
  return identity;
}
