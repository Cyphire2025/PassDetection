export type ApplicationDiagnosticCode =
  | 'APP_RENDER_FAILED'
  | 'APP_RECOVERY_REQUESTED'
  | 'APP_SIGN_OUT_REQUESTED'
  | 'APP_RESTART_REQUESTED'
  | 'APP_RECOVERY_ACTION_FAILED';

export type ApplicationDiagnostic = Readonly<{
  code: ApplicationDiagnosticCode;
  attempt: number;
}>;

const MAX_DIAGNOSTICS = 20;
const diagnostics: ApplicationDiagnostic[] = [];

/**
 * Keeps a small, process-local operational trail without accepting an Error,
 * message, stack, route, account identifier, filename, or arbitrary metadata.
 * This deliberately cannot become a channel for PII or native diagnostics.
 */
export function recordApplicationDiagnostic(
  code: ApplicationDiagnosticCode,
  attempt: number,
): void {
  diagnostics.push(Object.freeze({
    code,
    attempt: Math.max(0, Math.min(3, Math.trunc(attempt))),
  }));
  if (diagnostics.length > MAX_DIAGNOSTICS) diagnostics.splice(0, diagnostics.length - MAX_DIAGNOSTICS);
}

export function recentApplicationDiagnostics(): readonly ApplicationDiagnostic[] {
  return diagnostics.slice();
}

export function clearApplicationDiagnosticsForTests(): void {
  diagnostics.length = 0;
}
