"use client";

import { useState } from "react";
import { useMessageComposer } from "./use-message-composer";
import { ComposerAudience } from "./message-composer-audience";
import type { MessageDefinition } from "./composer.api";
import { MessageComposerEditor } from "./message-composer-editor";
import { MessageComposerFeedback } from "./message-composer-feedback";
import { MessageComposerReviewDialog } from "./message-composer-review-dialog";

export type ComposerController = ReturnType<typeof useMessageComposer>;

export function BroadcastMessageComposer({
  definition,
}: {
  definition: MessageDefinition;
}) {
  const model = useMessageComposer(definition);
  const [checkedHistory, setCheckedHistory] = useState(false);
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">
          {definition.label}
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          {definition.description}
        </p>
      </div>
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (model.ready || model.recovery) {
            setCheckedHistory(false);
            model.setReviewing(true);
          }
        }}
      >
        <MessageComposerEditor model={model} />
        <ComposerAudience model={model} />
        <MessageComposerFeedback model={model} />
      </form>
      {model.reviewing && <MessageComposerReviewDialog model={model} checkedHistory={checkedHistory} setCheckedHistory={setCheckedHistory} />}
    </div>
  );
}
