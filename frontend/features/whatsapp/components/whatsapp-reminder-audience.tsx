"use client";

import { CheckCircle2, Link2, UsersRound } from "lucide-react";
import { useId } from "react";
import type {
  WhatsAppLinkedClientGroup,
  WhatsAppReminderAudience,
} from "../api/whatsapp.api";

interface ReminderAudienceSelectorProps {
  audience: WhatsAppReminderAudience;
  audienceClientGroupId: string | null;
  linkedClientGroups: WhatsAppLinkedClientGroup[];
  eligibleRecipientCount: number;
  audienceRecipientCount: number | null;
  excludedSubmittedCount: number;
  excludedNeedsReviewCount: number;
  isLoadingGroups: boolean;
  isPreviewCurrent: boolean;
  disabled?: boolean;
  onAudienceChange: (audience: WhatsAppReminderAudience) => void;
  onClientGroupChange: (clientGroupId: string) => void;
}

export function ReminderAudienceSelector({
  audience,
  audienceClientGroupId,
  linkedClientGroups,
  eligibleRecipientCount,
  audienceRecipientCount,
  excludedSubmittedCount,
  excludedNeedsReviewCount,
  isLoadingGroups,
  isPreviewCurrent,
  disabled = false,
  onAudienceChange,
  onClientGroupChange,
}: ReminderAudienceSelectorProps) {
  const fieldsetDescriptionId = useId();
  const clientGroupSelectId = useId();
  const canUseNotSubmitted = linkedClientGroups.length > 0 && !isLoadingGroups;

  return (
    <fieldset
      className="min-w-0 rounded-xl border border-slate-200 bg-white p-3.5"
      aria-describedby={fieldsetDescriptionId}
      disabled={disabled}
    >
      <legend className="px-1 text-sm font-semibold text-slate-800">
        Reminder audience
      </legend>
      <p id={fieldsetDescriptionId} className="mt-1 text-xs leading-5 text-slate-500">
        Choose the audience here, review the personalised preview, then send.
      </p>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <label className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition ${
          audience === "all"
            ? "border-blue-300 bg-blue-50 ring-1 ring-blue-100"
            : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
        }`}>
          <input
            type="radio"
            name={`reminder-audience-${fieldsetDescriptionId}`}
            value="all"
            checked={audience === "all"}
            onChange={() => onAudienceChange("all")}
            className="mt-1 h-4 w-4 border-slate-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <UsersRound className="h-4 w-4 text-blue-700" aria-hidden="true" />
              Send to everyone
            </span>
            <span className="mt-1 block text-xs leading-5 text-slate-500">
              All active recipients, including people already identified as submitted.
            </span>
          </span>
        </label>

        <label className={`flex items-start gap-3 rounded-xl border p-3 transition ${
          audience === "not_submitted"
            ? "border-emerald-300 bg-emerald-50 ring-1 ring-emerald-100"
            : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
        } ${canUseNotSubmitted && !disabled ? "cursor-pointer" : "cursor-not-allowed opacity-60"}`}>
          <input
            type="radio"
            name={`reminder-audience-${fieldsetDescriptionId}`}
            value="not_submitted"
            checked={audience === "not_submitted"}
            disabled={!canUseNotSubmitted || disabled}
            onChange={() => onAudienceChange("not_submitted")}
            className="mt-1 h-4 w-4 border-slate-300 text-emerald-600 focus:ring-emerald-500"
          />
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <CheckCircle2 className="h-4 w-4 text-emerald-700" aria-hidden="true" />
              Only people who haven&apos;t submitted
            </span>
            <span className="mt-1 block text-xs leading-5 text-slate-500">
              Uses a linked passport group and rechecks identified submissions when you send.
            </span>
          </span>
        </label>
      </div>

      {isLoadingGroups ? (
        <p role="status" className="mt-3 text-xs text-slate-500">
          Checking linked passport groups…
        </p>
      ) : linkedClientGroups.length === 0 ? (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          <Link2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          Link this broadcast to a passport upload group before sending only to people who
          haven&apos;t submitted.
        </div>
      ) : audience === "not_submitted" && linkedClientGroups.length > 1 ? (
        <label htmlFor={clientGroupSelectId} className="mt-3 block text-xs font-semibold text-slate-700">
          Passport upload group used to check submissions
          <select
            id={clientGroupSelectId}
            value={audienceClientGroupId ?? ""}
            required
            onChange={(event) => onClientGroupChange(event.target.value)}
            className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-normal text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">Choose a linked passport group</option>
            {linkedClientGroups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </label>
      ) : audience === "not_submitted" ? (
        <p className="mt-3 text-xs leading-5 text-slate-600">
          Submission status will be checked against <strong>{linkedClientGroups[0]?.name}</strong>.
        </p>
      ) : null}

      {isPreviewCurrent && audienceRecipientCount !== null ? (
        <p
          role="status"
          aria-live="polite"
          className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600"
        >
          <strong className="text-slate-800">
            {eligibleRecipientCount.toLocaleString()} ready to receive
          </strong>
          {` from ${audienceRecipientCount.toLocaleString()} in this audience.`}
          {audience === "not_submitted" && excludedSubmittedCount > 0
            ? ` ${excludedSubmittedCount.toLocaleString()} submitted recipient${excludedSubmittedCount === 1 ? " was" : "s were"} excluded.`
            : ""}
          {audience === "not_submitted" && excludedNeedsReviewCount > 0
            ? ` ${excludedNeedsReviewCount.toLocaleString()} ambiguous recipient${excludedNeedsReviewCount === 1 ? " was" : "s were"} also excluded for safety.`
            : ""}
        </p>
      ) : audience === "not_submitted" && audienceClientGroupId ? (
        <p role="status" className="mt-3 text-xs leading-5 text-slate-500">
          Checking the latest submission status and recipient eligibility…
        </p>
      ) : null}

      {audience === "not_submitted" ? (
        <p className="mt-2 text-[11px] leading-5 text-slate-500">
          This audience contains only people confirmed as not submitted. Identified and
          ambiguous matches are both excluded so someone who may have submitted is not
          reminded accidentally.
        </p>
      ) : null}
    </fieldset>
  );
}
