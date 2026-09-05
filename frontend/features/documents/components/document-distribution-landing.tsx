import {
  ArrowLeft,
  ArrowRight,
  FileCheck2,
  FileStack,
  Plane,


} from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import { ROUTES } from "@/constants/routes";

const DISTRIBUTION_CATEGORIES = [
  {
    title: "Visa",
    description:
      "Open a group to check, match, review, and distribute passenger visa PDFs.",
    href: ROUTES.dashboard.documentDistributionVisa,
    icon: FileCheck2,
    action: "Choose a visa group",
    detail: "Review and distribute visas by group",
  },
  {
    title: "Flight Tickets",
    description:
      "Choose a group, then manage International or Domestic tickets as Onward and Return journeys.",
    href: ROUTES.dashboard.documentDistributionFlightTickets,
    icon: Plane,
    action: "Choose a flight-ticket group",
    detail: "Existing ticket uploads remain under International",
  },
] as const;

export function DocumentDistributionLanding() {
  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title="Document Distribution"
        description="Choose visas or flight tickets, then select a group to review and distribute its documents."
        icon={FileStack}
        accent="cyan"
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.documents}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Document Hub
          </IntentPrefetchLink>
        )}
      />

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="distribution-category-heading"
      >
        <div className="border-b border-slate-200 bg-slate-50/70 px-4 py-3.5 sm:px-5">

          <h2 id="distribution-category-heading" className="mt-0.5 font-semibold text-slate-950">
            What do you want to distribute?
          </h2>
        </div>

        <div className="grid lg:grid-cols-2">
          {DISTRIBUTION_CATEGORIES.map((category, index) => {
            const Icon = category.icon;
            return (
              <article
                key={category.href}
                className={index === 0
                  ? "border-b border-slate-200 p-5 sm:p-6 lg:border-b-0 lg:border-r"
                  : "p-5 sm:p-6"}
              >
                <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
                  <Icon className="h-6 w-6" aria-hidden="true" />
                </span>
                <h3 className="mt-4 text-xl font-semibold text-slate-950">{category.title}</h3>
                <p className="mt-2 min-h-12 text-sm leading-6 text-slate-600">
                  {category.description}
                </p>
                <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50/60 px-3 py-2 text-sm font-medium text-blue-800">
                  {category.detail}
                </div>
                <IntentPrefetchLink
                  href={category.href}
                  className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700"
                >
                  {category.action}
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </IntentPrefetchLink>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}
