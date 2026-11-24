import { returningApi } from "../api/returning.api";
import type { ClaimStart, ClaimTransition, MaskedCandidates, ReturningHistory } from "../types";

type TransitionContext = {
  method: ClaimStart["method"];
  groupToken?: string;
  signal: AbortSignal;
  setTransition: (transition: ClaimTransition) => void;
  setCandidates: (candidates: MaskedCandidates) => void;
  setHistory: (history: ReturningHistory) => void;
};

/** Follow server-selected progress once; a repeated automatic stage needs an explicit retry. */
export async function resolveReturningTransition(initial: ClaimTransition, context: TransitionContext): Promise<void> {
  const { method, groupToken, signal, setTransition, setCandidates, setHistory } = context;
  const automaticStages = new Set<ClaimTransition["stage"]>();
  let next = initial;
  const enterAutomaticStage = () => {
    if (automaticStages.has(next.stage)) {
      throw new Error("Your saved-document verification did not advance. Please retry this step or choose another verification option.");
    }
    automaticStages.add(next.stage);
  };

  while (!signal.aborted) {
    setTransition(next);
    if (next.stage === "confirm" || next.stage === "recovery") {
      enterAutomaticStage();
      next = await returningApi.authorize(signal);
      continue;
    }
    if (next.stage === "identify") {
      if (method === "passport") {
        enterAutomaticStage();
        next = await returningApi.passport({}, signal);
        continue;
      }
      if (method === "code") {
        setTransition({ stage: "passport" });
        return;
      }
      const candidates = await returningApi.candidates(signal);
      if (signal.aborted) return;
      setCandidates(candidates);
      setTransition({ stage: candidates.narrowing_required || candidates.items.length === 0 ? "passport" : "identify" });
      return;
    }
    if (next.stage === "review") {
      const history = await returningApi.history(signal, groupToken);
      if (!signal.aborted) setHistory(history);
    }
    if (!signal.aborted) setTransition(next);
    return;
  }
}
