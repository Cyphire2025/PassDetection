"use client";
import { EmptyState } from "@/components/shared/empty-state";
import { Button, Card, CardContent, Skeleton } from "@/components/ui";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import { Eye, FileText, UploadCloud } from "lucide-react";
import Link from "next/link";
import { Fragment } from "react";
import {
  DuplicateClusterHeader,
  PassportDocumentMatrix,
  PassportMobileCard,
  ReextractPassportControl,
  StatusBadge,
  getDashboardCountry,
  getDashboardFields,
  getDashboardPassportDate,
  getStringField,
  isDuplicateClusterStart,
  isDuplicatePassport,
} from "./passport-group-model";
import type { PassportGroupController } from "./use-passport-group-controller";
export function PassportGroupRosterPanel({
  error,
  isLoading,
  submissionsView,
  data,
  setSearch,
  setDebouncedSearch,
  setSubmissionFilter,
  setSortBy,
  setSortOrder,
  setPage,
  viewMode,
  filteredPassports,
  canEditImages,
  includeDeleted,
  imageRevision,
  setImageEditor,
  debouncedSearch,
  selectedPassportIdSet,
  togglePassport,
  passportDetailHref,
  persistNavigationContext,
  page,
  isFetching,
}: Pick<
  PassportGroupController,
  | "error"
  | "isLoading"
  | "submissionsView"
  | "data"
  | "setSearch"
  | "setDebouncedSearch"
  | "setSubmissionFilter"
  | "setSortBy"
  | "setSortOrder"
  | "setPage"
  | "viewMode"
  | "filteredPassports"
  | "canEditImages"
  | "includeDeleted"
  | "imageRevision"
  | "setImageEditor"
  | "debouncedSearch"
  | "selectedPassportIdSet"
  | "togglePassport"
  | "passportDetailHref"
  | "persistNavigationContext"
  | "page"
  | "isFetching"
>) {
  return (
    <>
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load passport submissions for this group.
        </div>
      )}
      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
      ) : error ? null : (submissionsView?.group_total ?? 0) === 0 ? (
        <EmptyState
          icon={<UploadCloud className="h-5 w-5" />}
          title="Drop passport here"
          description="Share this group link with clients or upload a passport through the client page. Submitted passports will appear here."
        />
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="No passports match these filters"
          description="Adjust the search or submission filter to find more submissions."
          action={{
            label: "Reset Filters",
            onClick: () => {
              setSearch("");
              setDebouncedSearch("");
              setSubmissionFilter("all");
              setSortBy("name");
              setSortOrder("asc");
              setPage(1);
            },
          }}
        />
      ) : viewMode === "docs" ? (
        <PassportDocumentMatrix
          passports={filteredPassports}
          canEdit={canEditImages && !includeDeleted}
          revision={imageRevision}
          onEdit={(submissionId, imageType, label, returnFocusTarget) => {
            setImageEditor({
              submissionId,
              imageType,
              label,
              returnFocusTarget,
            });
          }}
        />
      ) : (
        <>
          <div className="grid gap-4 lg:hidden">
            {filteredPassports.map((passport, index) => (
              <Fragment key={passport.id}>
                {isDuplicateClusterStart(filteredPassports, index) && (
                  <DuplicateClusterHeader
                    passport={passport}
                    searchActive={Boolean(debouncedSearch)}
                  />
                )}
                <PassportMobileCard
                  passport={passport}
                  selected={selectedPassportIdSet.has(passport.id)}
                  onToggle={() => togglePassport(passport.id)}
                  detailHref={passportDetailHref(passport.id)}
                  onOpen={persistNavigationContext}
                />
              </Fragment>
            ))}
          </div>

          <Card className="hidden lg:block">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">
                    Group passenger passport readiness
                  </caption>
                  <thead>
                    <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                      <th scope="col" className="px-6 py-4">
                        Client
                      </th>
                      <th scope="col" className="px-6 py-4">
                        Status
                      </th>
                      <th scope="col" className="px-6 py-4">
                        Passport
                      </th>
                      <th scope="col" className="px-6 py-4">
                        Passport Dates
                      </th>
                      <th scope="col" className="px-6 py-4">
                        Confidence
                      </th>
                      <th scope="col" className="px-6 py-4">
                        Updated
                      </th>
                      <th scope="col" className="px-6 py-4 text-right">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filteredPassports.map((passport, index) => (
                      <Fragment key={passport.id}>
                        {isDuplicateClusterStart(filteredPassports, index) && (
                          <tr className="border-y border-amber-200 bg-amber-50">
                            <td colSpan={7} className="px-6 py-2">
                              <DuplicateClusterHeader
                                passport={passport}
                                searchActive={Boolean(debouncedSearch)}
                                compact
                              />
                            </td>
                          </tr>
                        )}
                        <tr
                          className={`cursor-pointer hover:bg-slate-50/60 ${
                            isDuplicatePassport(passport)
                              ? "bg-amber-50/30"
                              : ""
                          }`}
                          onClick={() => togglePassport(passport.id)}
                        >
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <input
                                type="checkbox"
                                checked={selectedPassportIdSet.has(passport.id)}
                                onChange={() => togglePassport(passport.id)}
                                onClick={(event) => event.stopPropagation()}
                                aria-label={`Select ${passport.client_name}`}
                                className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                              />
                              <div className="min-w-0">
                                <div className="font-semibold text-slate-900">
                                  {passport.client_name}
                                </div>
                                <div className="mt-1 break-all text-xs text-slate-500">
                                  {passport.client_email ?? "No email provided"}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <StatusBadge status={passport.status} />
                          </td>
                          <td className="px-6 py-4">
                            <div className="font-medium text-slate-800">
                              {getStringField(
                                getDashboardFields(passport),
                                "passport_number",
                              ) || "Not extracted"}
                            </div>
                            <div className="mt-1 text-xs text-slate-500">
                              {getDashboardCountry(passport) || "Manual review"}
                            </div>
                          </td>
                          <td className="px-6 py-4 text-xs text-slate-600">
                            <div>
                              <span className="font-medium text-slate-500">
                                DOB:
                              </span>{" "}
                              {getDashboardPassportDate(
                                passport,
                                "date_of_birth",
                              )}
                            </div>
                            <div className="mt-1">
                              <span className="font-medium text-slate-500">
                                Issued:
                              </span>{" "}
                              {getDashboardPassportDate(
                                passport,
                                "date_of_issue",
                              )}
                            </div>
                            <div className="mt-1">
                              <span className="font-medium text-slate-500">
                                Expires:
                              </span>{" "}
                              {getDashboardPassportDate(
                                passport,
                                "date_of_expiry",
                              )}
                            </div>
                          </td>
                          <td className="px-6 py-4 text-slate-700">
                            {formatConfidence(
                              passport.verification_confidence ?? null,
                            )}
                          </td>
                          <td className="px-6 py-4 text-slate-500">
                            {formatDateTime(passport.updated_at)}
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center justify-end gap-2">
                              <ReextractPassportControl
                                passport={passport}
                                compact
                              />
                              <Link
                                href={passportDetailHref(passport.id) as never}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  persistNavigationContext();
                                }}
                              >
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="gap-2"
                                >
                                  <Eye className="h-4 w-4" />
                                  Open
                                </Button>
                              </Link>
                            </div>
                          </td>
                        </tr>
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
      {submissionsView && submissionsView.total > 0 && (
        <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-slate-600">
            Showing {submissionsView.items.length.toLocaleString()} of{" "}
            {submissionsView.total.toLocaleString()} matching submissions
            {submissionsView.cluster_boundaries_preserved
              ? " · duplicate sets stay together"
              : ""}
          </p>
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={page <= 1 || isFetching}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </Button>
            <span className="min-w-24 text-center text-sm font-medium text-slate-700">
              Page {submissionsView.page} of{" "}
              {Math.max(1, submissionsView.total_pages)}
            </span>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={page >= submissionsView.total_pages || isFetching}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
