import { Skeleton } from "@/components/ui";

export default function GcAppLoading() {
  return (
    <div aria-label="Loading GC App" className="space-y-4">
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}
