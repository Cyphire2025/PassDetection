import { Skeleton } from "@/components/ui";

export default function CoordinatorLoading() {
  return (
    <div data-coordinator-shell className="bg-slate-100 text-slate-950">
      <div className="mx-auto flex min-h-dvh w-full max-w-lg flex-col bg-slate-50 px-[max(1rem,env(safe-area-inset-left))] pb-[max(1rem,env(safe-area-inset-bottom))] pt-[max(1rem,env(safe-area-inset-top))] pr-[max(1rem,env(safe-area-inset-right))]">
        <div className="flex items-center justify-between">
          <Skeleton className="h-11 w-11 rounded-full" />
          <Skeleton className="h-6 w-20 rounded-full" />
        </div>
        <Skeleton className="mt-5 h-6 w-44 rounded-md" />
        <Skeleton className="mt-2 h-4 w-64 max-w-full rounded-md" />
        <div className="mt-6 grid grid-cols-2 gap-3">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-20 rounded-xl" />
        </div>
        <Skeleton className="mt-4 h-52 rounded-xl" />
        <p className="sr-only" role="status">Loading coordinator workspace</p>
      </div>
    </div>
  );
}
