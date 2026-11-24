import { DocumentFollowUpBadge } from "./passport-document-follow-up";
import { buttonVariants, Card, CardContent } from "@/components/ui";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import { Eye } from "lucide-react";
import Link from "next/link";
import { Fragment } from "react";
import {
  DuplicateClusterHeader,
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

type Props = Pick<
  PassportGroupController,
  | "filteredPassports"
  | "debouncedSearch"
  | "selectedPassportIdSet"
  | "togglePassport"
  | "passportDetailHref"
  | "persistNavigationContext"
>;

export function PassportGroupRosterTable({
  filteredPassports,
  debouncedSearch,
  selectedPassportIdSet,
  togglePassport,
  passportDetailHref,
  persistNavigationContext,
}: Props) {
  return (
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
                            aria-label={`Select ${passport.display_name || passport.client_name}`}
                            className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                          />
                          <div className="min-w-0">
                            <div className="font-semibold text-slate-900">
                              {passport.display_name || passport.client_name}
                            </div>
                            <DocumentFollowUpBadge flagged={passport.document_follow_up} />
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
                            href={passportDetailHref(passport.id)}
                            className={buttonVariants({ variant: "outline", size: "sm", className: "gap-2" })}
                            onClick={(event) => {
                              event.stopPropagation();
                              persistNavigationContext();
                            }}
                          >
                            <Eye className="h-4 w-4" aria-hidden="true" />
                            Open
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
  );
}
