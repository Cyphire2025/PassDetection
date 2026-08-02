export function redirectSystemPath({ path }: { path: string; initial: boolean }): string {
  try {
    const url = new URL(path, 'groupcompanion://');
    if (url.pathname === '/gc/activate' || url.pathname === '/activate' || url.hostname === 'activate') {
      const token = url.searchParams.get('token');
      return token ? `/activate?token=${encodeURIComponent(token)}` : '/activate';
    }
  } catch {
    // Malformed external paths are routed to the safe welcome screen.
  }
  return '/';
}
