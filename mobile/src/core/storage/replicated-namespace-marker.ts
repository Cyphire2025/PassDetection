type PrivateMarkerFile = Readonly<{
  uri: string;
  exists: boolean;
  create: (options: { overwrite: boolean; intermediates: boolean }) => void;
  delete: () => void;
  text: () => Promise<string>;
  write: (value: string) => void;
}>;

type ReplicatedNamespaceMarkerOptions = Readonly<{
  assertNamespace: (namespace: string) => void;
  errorMessage: string;
  excludeFromBackup: (uri: string) => Promise<void>;
  file: PrivateMarkerFile;
  mutate: <T>(operation: () => Promise<T>) => Promise<T>;
  readSecureReplica: () => Promise<string | null>;
  writeSecureReplica: (encoded: string) => Promise<void>;
}>;

function parseNamespaceList(encoded: string | null): string[] {
  if (!encoded) return [];
  try {
    const parsed: unknown = JSON.parse(encoded);
    if (!Array.isArray(parsed)) throw new Error('Invalid namespace list.');
    const valid = parsed.filter(
      (value): value is string => (
        typeof value === 'string' && /^[0-9a-f-]{36}\.[0-9a-f-]{36}$/i.test(value)
      ),
    );
    if (valid.length !== parsed.length) throw new Error('Invalid namespace list.');
    return valid;
  } catch {
    throw new Error('Secure authentication-lock state is unavailable.');
  }
}

export function createReplicatedNamespaceMarker(options: ReplicatedNamespaceMarkerOptions) {
  const read = async (): Promise<string[]> => {
    const combined = new Set<string>();
    let secureReadable = false;
    let fileReadable = false;
    let firstError: unknown;
    try {
      for (const namespace of parseNamespaceList(await options.readSecureReplica())) {
        combined.add(namespace);
      }
      secureReadable = true;
    } catch (error) {
      firstError = error;
    }
    try {
      const encoded = options.file.exists ? await options.file.text() : null;
      for (const namespace of parseNamespaceList(encoded)) combined.add(namespace);
      fileReadable = true;
    } catch (error) {
      firstError ??= error;
    }
    if (!secureReadable && !fileReadable) throw firstError;
    return [...combined];
  };

  const write = async (pending: string[], requireEveryReplica: boolean): Promise<void> => {
    const encoded = JSON.stringify(pending);
    let secureWritten = false;
    let fileWritten = false;
    let firstError: unknown;
    try {
      await options.writeSecureReplica(encoded);
      secureWritten = true;
    } catch (error) {
      firstError = error;
    }
    try {
      options.file.create({ overwrite: true, intermediates: true });
      options.file.write(encoded);
      await options.excludeFromBackup(options.file.uri);
      fileWritten = true;
    } catch (error) {
      firstError ??= error;
      try {
        if (options.file.exists) options.file.delete();
      } catch {
        // Preserve the original persistence or backup-exclusion error.
      }
    }
    if (
      (!secureWritten && !fileWritten)
      || (requireEveryReplica && (!secureWritten || !fileWritten))
    ) {
      throw firstError ?? new Error(options.errorMessage);
    }
  };

  return Object.freeze({
    get: read,
    mark: (namespace: string): Promise<void> => {
      options.assertNamespace(namespace);
      return options.mutate(async () => {
        const pending = new Set(await read());
        pending.add(namespace);
        await write([...pending], false);
      });
    },
    clear: (namespace: string): Promise<void> => {
      options.assertNamespace(namespace);
      return options.mutate(async () => {
        const pending = (await read()).filter((value) => value !== namespace);
        await write(pending, true);
      });
    },
  });
}
