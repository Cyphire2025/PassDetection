import type { PassportSubmission } from "@/types/passport.types";

export function isDuplicatePassport(passport: PassportSubmission) {
  return Boolean(
    passport.duplicate_cluster_id && (passport.duplicate_cluster_size ?? 0) > 1,
  );
}

export function isDuplicateClusterStart(
  passports: PassportSubmission[],
  index: number,
) {
  const passport = passports[index];
  if (!passport || !isDuplicatePassport(passport)) return false;
  return (
    index === 0 ||
    passports[index - 1]?.duplicate_cluster_id !== passport.duplicate_cluster_id
  );
}

export function DuplicateClusterHeader({
  passport,
  searchActive,
  compact = false,
}: {
  passport: PassportSubmission;
  searchActive: boolean;
  compact?: boolean;
}) {
  const count =
    passport.duplicate_cluster_size ??
    passport.duplicate_cluster_member_ids?.length ??
    2;
  return (
    <div
      className={
        compact
          ? "flex flex-wrap items-center gap-2"
          : "rounded-xl border border-amber-200 bg-amber-50 px-4 py-3"
      }
    >
      <span className="inline-flex items-center rounded-full bg-amber-200/70 px-2.5 py-1 text-xs font-bold text-amber-950">
        Possible duplicate set
      </span>
      <span className="text-xs font-medium text-amber-900">
        Part of a possible duplicate set with {count} submissions
        {searchActive
          ? " · search includes this set; status filters still apply"
          : ""}
      </span>
    </div>
  );
}
