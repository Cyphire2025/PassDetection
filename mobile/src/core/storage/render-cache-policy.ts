export function shouldPurgeDiskCacheForAccountTransition(input: {
  previousAccount: string | null;
  nextAccount: string | null;
  hasActivatedAccount: boolean;
}): boolean {
  // Startup already performs the one legacy disk-cache migration purge. The
  // first null -> account activation (restored session or first login) only
  // needs the normal plaintext/memory cleanup. Every later logout or account
  // replacement retains the stronger disk purge boundary.
  return input.previousAccount !== null || input.hasActivatedAccount;
}
