import { Badge, Button } from "@/components/ui";
import type { EmailAiRolloutTarget } from "../types";
import { Definition } from "./email-integrations-ui";
import { nextDirectEnabled, rolloutExplanation } from "./email-rollout-model";

export function EmailRolloutTarget({ target, pending, isUpdating, onDecision }: {
  target: EmailAiRolloutTarget;
  pending: boolean;
  isUpdating: boolean;
  onDecision: (target: EmailAiRolloutTarget, enabled: boolean) => void;
}) {
  const nextEnabled = nextDirectEnabled(target);
  return (
    <li
      className="rounded-xl border border-slate-200 bg-white p-4"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="break-words font-semibold text-slate-950">
            {target.label}
          </h3>
          {target.detail && (
            <p className="mt-1 break-words text-sm text-slate-600">
              {target.detail}
            </p>
          )}
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <Definition term="Rule at this level">
              <DirectRuleBadge
                directEnabled={target.direct_enabled}
              />
            </Definition>
            <Definition term="Effective state">
              <Badge
                variant={
                  target.effective_enabled
                    ? "success"
                    : "warning"
                }
                dot
              >
                {target.effective_enabled
                  ? "Rollout allowed"
                  : "Rollout paused"}
              </Badge>
            </Definition>
          </dl>
          <p className="mt-3 text-xs leading-5 text-slate-500">
            {rolloutExplanation(target)}
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant={nextEnabled ? "primary" : "danger"}
          className="shrink-0"
          isLoading={isUpdating}
          disabled={pending}
          onClick={() => onDecision(target, nextEnabled)}
        >
          {nextEnabled ? "Allow" : "Pause"}
        </Button>
      </div>
    </li>
  );
}

function DirectRuleBadge({
  directEnabled,
}: {
  directEnabled: boolean | null;
}) {
  if (directEnabled === null) {
    return <Badge variant="outline">Inherited</Badge>;
  }
  return (
    <Badge variant={directEnabled ? "success" : "warning"} dot>
      {directEnabled ? "Allowed here" : "Paused here"}
    </Badge>
  );
}

