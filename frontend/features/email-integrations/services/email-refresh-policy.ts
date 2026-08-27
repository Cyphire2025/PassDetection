const ACTIVE_REPAIR_MIN_MS = 5_000;
const ACTIVE_REPAIR_MAX_MS = 10_000;
const IDLE_REPAIR_MIN_MS = 30_000;
const IDLE_REPAIR_MAX_MS = 60_000;

interface EmailRefreshPolicyOptions {
  active?: boolean;
  random?: () => number;
  visible?: boolean;
}

/**
 * Return a fully-jittered repair interval for email projections.
 *
 * Email state remains server-authoritative. Polling is deliberately a slow
 * convergence lane rather than a synchronized five-second data plane; direct
 * mutations still invalidate the exact query family immediately. Background
 * documents never schedule repair work.
 */
export function emailRepairIntervalMs({
  active = false,
  random = Math.random,
  visible = isDocumentVisible(),
}: EmailRefreshPolicyOptions = {}): number | false {
  if (!visible) return false;
  const minimum = active ? ACTIVE_REPAIR_MIN_MS : IDLE_REPAIR_MIN_MS;
  const maximum = active ? ACTIVE_REPAIR_MAX_MS : IDLE_REPAIR_MAX_MS;
  const sample = Math.min(Math.max(random(), 0), 1);
  return Math.round(minimum + (maximum - minimum) * sample);
}

function isDocumentVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

export const EMAIL_REPAIR_PAGE_BUDGET = 5;
