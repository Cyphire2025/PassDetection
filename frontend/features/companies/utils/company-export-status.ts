import type { CompanyDataExport } from "../api/company-data-exports.api";

const RUNNING = new Set<CompanyDataExport["status"]>(["queued", "running"]);
export const COMPANY_EXPORT_STATUS: Record<CompanyDataExport["status"], string> = {
  queued: "Queued",
  running: "Preparing",
  succeeded: "Ready",
  failed: "Failed",
  cancelled: "Cancelled",
  expired: "Expired",
};

export function companyExportRunning(status: CompanyDataExport["status"]) {
  return RUNNING.has(status);
}
