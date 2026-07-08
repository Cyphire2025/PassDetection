"use client";

import Link from "next/link";
import { ExternalLink, ListChecks, QrCode, UserPlus, UsersRound } from "lucide-react";
import { Badge, Card, CardContent, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { useTourCoordinators, useTourGroups } from "../hooks/use-operations";
import { getTourGroupTotals, TourMetric } from "./tour-operations-ui";

const workflows = [
  {
    title: "Coordinators",
    description: "Create and review field coordinator login accounts.",
    href: ROUTES.dashboard.tourOperationsCoordinators,
    icon: UserPlus,
  },
  {
    title: "Group Assignments",
    description: "Assign specific coordinators to each tour group.",
    href: ROUTES.dashboard.tourOperationsGroupAssignments,
    icon: ListChecks,
  },
  {
    title: "Scanner PWA",
    description: "Open the mobile scanner workflow used by coordinators.",
    href: "/tour-scanner",
    icon: QrCode,
    external: true,
  },
];

export function TourOperationsOverview() {
  const { data: coordinators = [], isLoading: coordinatorsLoading } = useTourCoordinators();
  const { data: groups = [], isLoading: groupsLoading } = useTourGroups();
  const totals = getTourGroupTotals(groups);
  const loading = coordinatorsLoading || groupsLoading;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tour Operations"
        description="Coordinator-led group assignment and passenger allocation."
        actions={<Badge variant="secondary">Phase 3</Badge>}
      />

      <div className="grid gap-4 md:grid-cols-4">
        {loading ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[90px] rounded-xl" />)
        ) : (
          <>
            <TourMetric label="Groups" value={totals.groups} />
            <TourMetric label="Coordinators" value={coordinators.length} />
            <TourMetric label="Passport Submitted" value={totals.passengers} />
            <TourMetric label="Unassigned" value={totals.unassigned} tone={totals.unassigned > 0 ? "warning" : "default"} />
          </>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {workflows.map((workflow) => {
          const Icon = workflow.icon;
          const content = (
            <Card className="h-full transition hover:border-blue-200 hover:shadow-md">
              <CardContent className="flex h-full flex-col gap-5 p-5">
                <div className="flex items-start justify-between gap-4">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  {workflow.external && <ExternalLink className="h-4 w-4 text-slate-400" aria-hidden="true" />}
                </div>
                <div>
                  <h3 className="text-base font-semibold text-slate-900">{workflow.title}</h3>
                  <p className="mt-1 text-sm leading-6 text-slate-500">{workflow.description}</p>
                </div>
              </CardContent>
            </Card>
          );

          return workflow.external ? (
            <Link key={workflow.title} href={workflow.href as never} target="_blank" className="block">
              {content}
            </Link>
          ) : (
            <Link key={workflow.title} href={workflow.href as never} className="block">
              {content}
            </Link>
          );
        })}
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="flex items-center gap-3 border-b border-slate-200 p-5">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
              <UsersRound className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-base font-semibold text-slate-900">Operational Flow</h2>
              <p className="text-sm text-slate-500">Create coordinators, assign them to groups, then allocate passengers inside each group.</p>
            </div>
          </div>
          <div className="grid gap-0 divide-y divide-slate-100 md:grid-cols-3 md:divide-x md:divide-y-0">
            {["Create coordinator accounts", "Assign coordinators to groups", "Open group and assign passengers"].map((step, index) => (
              <div key={step} className="p-5">
                <p className="text-xs font-semibold uppercase text-blue-600">Step {index + 1}</p>
                <p className="mt-2 text-sm font-medium text-slate-900">{step}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
