type AccessDeniedHandler = (path: string, status: number) => Promise<void>;

let accessDeniedHandler: AccessDeniedHandler | null = null;

export function registerAccessDeniedHandler(handler: AccessDeniedHandler): () => void {
  accessDeniedHandler = handler;
  return () => {
    if (accessDeniedHandler === handler) accessDeniedHandler = null;
  };
}

export async function handleAccessDenied(path: string, status: number): Promise<void> {
  if ((status === 401 || status === 403) && accessDeniedHandler) {
    await accessDeniedHandler(path, status).catch(() => undefined);
  }
}
