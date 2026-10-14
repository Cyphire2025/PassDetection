/** In-flight responses preserve newer local edits; separate-window saves reject conflicts. */
export function draftFieldValue<T>(before: T, local: T, remote: T, preserveLocal = false): T {
  if (local === before) return remote;
  if (!preserveLocal && remote !== before && remote !== local) {
    throw new Error("This draft was changed in another window. Reopen it to review the latest details before continuing.");
  }
  return local;
}
