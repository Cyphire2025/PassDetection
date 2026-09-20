"use client";

import { type ReactNode, useEffect } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { usePassportGroups } from "../hooks/use-passports";

/** Import-only groups have contacts, but no passport submission workflow. */
export function GroupWhatsAppTrackingGate({ groupId, children }: { groupId: string; children: ReactNode }) {
  const router = useRouter();
  const groups = usePassportGroups();
  const group = groups.data?.find((item) => item.group_id === groupId);

  useEffect(() => {
    if (group?.import_only) router.replace(ROUTES.dashboard.passportGroup(groupId) as never);
  }, [group?.import_only, groupId, router]);

  if (group?.import_only) return null;
  if (groups.isLoading) return <Skeleton className="h-44 w-full rounded-2xl" />;
  if (groups.isError || !group) {
    return (
      <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
        <p role="alert" className="text-sm text-slate-700">
          {groups.isError ? "Group details could not be loaded." : "This group is unavailable."}
        </p>
        {groups.isError && <Button type="button" variant="secondary" onClick={() => void groups.refetch()} isLoading={groups.isFetching}>Try again</Button>}
        <Link href={ROUTES.dashboard.passportGroup(groupId) as Route} className="block text-sm font-medium text-blue-700 hover:underline">Back to group</Link>
      </div>
    );
  }
  return children;
}
