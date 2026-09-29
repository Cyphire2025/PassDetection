"use client";
import { Badge, Card, CardContent } from "@/components/ui";
import { formatPassportDateForUi } from "@/lib/utils/passport-date";
import { AlertTriangle, ChevronDown } from "lucide-react";
import Link from "next/link";
import {
  PassportDocumentImportDialog,
  PassportDocumentImportProgress,
} from "./passport-group-bindings";
import type { PassportGroupController } from "./use-passport-group-controller";
export function PassportGroupImportPanel({
  passportImportProgress,
  passportImportPreview,
  passportImportFiles,
  passportSaveMutation,
  setPassportImportPreview,
  setPassportImportProgress,
  setImportMessage,
  setPassportImportFiles,
  expiryAlerts,
  isExpiryAlertsExpanded,
  expiryAlertsRegionId,
  setIsExpiryAlertsExpanded,
  groupDetails,
  passportDetailHref,
  persistNavigationContext,
}: Pick<
  PassportGroupController,
  | "passportImportProgress"
  | "passportImportPreview"
  | "passportImportFiles"
  | "passportSaveMutation"
  | "setPassportImportPreview"
  | "setPassportImportProgress"
  | "setImportMessage"
  | "setPassportImportFiles"
  | "expiryAlerts"
  | "isExpiryAlertsExpanded"
  | "expiryAlertsRegionId"
  | "setIsExpiryAlertsExpanded"
  | "groupDetails"
  | "passportDetailHref"
  | "persistNavigationContext"
>) {
  return (
    <>
      {passportImportProgress && (
        <PassportDocumentImportProgress
          processed={passportImportProgress.processed}
          total={passportImportProgress.total}
          label={passportImportProgress.label}
        />
      )}
      {passportImportPreview && (
        <PassportDocumentImportDialog
          preview={passportImportPreview}
          files={passportImportFiles}
          saving={passportSaveMutation.isPending}
          onClose={() => {
            if (!passportSaveMutation.isPending) setPassportImportPreview(null);
          }}
          onSave={() => {
            passportSaveMutation.mutate(
              {
                files: passportImportFiles,
                onProgress: (progress) => {
                  setPassportImportProgress({
                    processed: progress.loaded,
                    total: progress.total,
                    label:
                      progress.phase === "uploading"
                        ? "Uploading accepted documents"
                        : "Saving accepted documents",
                  });
                },
              },
              {
                onSuccess: (result) => {
                  setImportMessage(
                    `Saved ${result.saved_count} passport document${result.saved_count === 1 ? "" : "s"}. Rejected files were not stored.`,
                  );
                  setPassportImportPreview(null);
                  setPassportImportFiles([]);
                  setPassportImportProgress(null);
                },
                onError: (error) => {
                  setPassportImportProgress(null);
                  setImportMessage(
                    error instanceof Error
                      ? error.message
                      : "Could not save passport documents",
                  );
                },
              },
            );
          }}
        />
      )}
      {expiryAlerts.length > 0 && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="p-0">
            <button
              type="button"
              aria-expanded={isExpiryAlertsExpanded}
              aria-controls={expiryAlertsRegionId}
              onClick={() => setIsExpiryAlertsExpanded((current) => !current)}
              className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2"
            >
              <div className="flex min-w-0 items-center gap-3">
                <AlertTriangle
                  className="h-4 w-4 shrink-0 text-red-700"
                  aria-hidden="true"
                />
                <div>
                  <h2 className="text-sm font-semibold text-red-950">
                    Passport Expiry Alerts
                  </h2>
                  <p className="mt-0.5 text-xs leading-5 text-red-800">
                    {groupDetails?.travel_date
                      ? `Expired or expiring within 6 months of departure (${formatPassportDateForUi(groupDetails.travel_date)}).`
                      : "Expired or expiring within the next 6 months."}
                  </p>
                </div>
              </div>
              <span className="flex shrink-0 items-center gap-2">
                <Badge variant="destructive">{expiryAlerts.length}</Badge>
                <ChevronDown
                  className={`h-4 w-4 text-red-800 transition-transform ${
                    isExpiryAlertsExpanded ? "rotate-180" : ""
                  }`}
                  aria-hidden="true"
                />
              </span>
            </button>
            {isExpiryAlertsExpanded && (
              <div
                id={expiryAlertsRegionId}
                role="region"
                aria-label="Passports with expiry alerts"
                className="grid max-h-80 gap-3 overflow-y-auto overscroll-contain border-t border-red-200 p-4 md:grid-cols-2"
              >
                {expiryAlerts.map((passport) => (
                  <Link
                    key={passport.submission_id}
                    href={passportDetailHref(passport.submission_id)}
                    onClick={persistNavigationContext}
                    className="min-w-0 rounded-lg border border-red-200 bg-white p-3 hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="break-words text-sm font-semibold text-slate-900">
                          {passport.client_name}
                        </div>
                        <div className="break-words text-xs text-slate-500">
                          {passport.passport_number ||
                            "Passport number not extracted"}
                        </div>
                      </div>
                      <div className="text-right text-sm font-medium text-red-800">
                        {formatPassportDateForUi(passport.date_of_expiry) ||
                          "Expiry missing"}
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}
