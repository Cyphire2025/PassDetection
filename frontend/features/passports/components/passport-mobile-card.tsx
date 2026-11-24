import { DocumentFollowUpBadge } from "./passport-document-follow-up";
import { buttonVariants, Card, CardContent } from "@/components/ui";
import { formatConfidence, formatDateTime } from "@/lib/utils/format";
import type { PassportSubmission } from "@/types/passport.types";
import { Eye } from "lucide-react";
import Link from "next/link";
import { needsReextraction } from "../utils/passport-reextract";
import { isDuplicatePassport } from "./passport-group-duplicates";
import {
  InfoPair,
  StatusBadge,
  getDashboardFields,
  getStringField,
  getDashboardCountry,
  getDashboardPassportDate,
} from "./passport-group-fields";
import { ReextractPassportControl } from "./reextract-passport-control";

export function PassportMobileCard({
  passport,
  selected,
  onToggle,
  detailHref,
  onOpen,
}: {
  passport: PassportSubmission;
  selected: boolean;
  onToggle: () => void;
  detailHref: ReturnType<typeof import("../utils/passport-group-navigation").buildPassportDetailNavigationHref>;
  onOpen: () => void;
}) {
  const cardClassName = selected
    ? "rounded-2xl border-blue-300 bg-blue-50/40"
    : isDuplicatePassport(passport)
      ? "rounded-2xl border-amber-200 bg-amber-50/30"
      : "rounded-2xl";
  return (
    <Card className={cardClassName} onClick={onToggle}>
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex gap-3">
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              onClick={(event) => event.stopPropagation()}
              aria-label={`Select ${passport.display_name || passport.client_name}`}
              className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-slate-900">
                {passport.display_name || passport.client_name}
              </h3>
              <DocumentFollowUpBadge flagged={passport.document_follow_up} />
              <p className="mt-1 break-all text-xs text-slate-500">
                {passport.client_email ?? "No email provided"}
              </p>
            </div>
          </div>
          <StatusBadge status={passport.status} />
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <InfoPair
            label="Passport"
            value={
              getStringField(getDashboardFields(passport), "passport_number") ||
              "Not extracted"
            }
          />
          <InfoPair
            label="Nationality"
            value={getDashboardCountry(passport) || "Manual review"}
          />
          <InfoPair
            label="Confidence"
            value={formatConfidence(passport.verification_confidence ?? null)}
          />
          <InfoPair
            label="Updated"
            value={formatDateTime(passport.updated_at)}
          />
          <InfoPair
            label="Date of Birth"
            value={getDashboardPassportDate(passport, "date_of_birth")}
          />
          <InfoPair
            label="Date of Issue"
            value={getDashboardPassportDate(passport, "date_of_issue")}
          />
          <InfoPair
            label="Date of Expiry"
            value={getDashboardPassportDate(passport, "date_of_expiry")}
          />
        </div>

        <div
          className={`grid gap-2 ${needsReextraction(passport) || passport.extraction_status === "processing" ? "sm:grid-cols-2" : ""}`}
        >
          <ReextractPassportControl passport={passport} />
          <Link
            href={detailHref}
            className={buttonVariants({ variant: "outline", className: "w-full gap-2" })}
            onClick={(event) => {
              event.stopPropagation();
              onOpen();
            }}
          >
            <Eye className="h-4 w-4" aria-hidden="true" />
            Open Submission
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
