// @vitest-environment node
import { describe, expect, it } from "vitest";
import { evaluateFrontendModuleBudgets } from "../../../scripts/verify-frontend-module-budgets.mjs";

type ModuleBudget = Readonly<{ path: string; baselineLines: number; maximumLines: number; baselineMaxFunctionComplexity: number; maximumFunctionComplexity: number }>;
type BudgetMeasurement = ModuleBudget & Readonly<{ actualLines: number; actualMaxFunctionComplexity: number; withinBudget: boolean }>;
// The JavaScript default parameter infers only its existing literal path union.
const evaluateBudgets = evaluateFrontendModuleBudgets as (budgets: readonly ModuleBudget[]) => readonly BudgetMeasurement[];

// Additive draft and document budgets share the established evaluator. Keep the
// existing release-script ceilings unchanged and run these with feature tests.
const draftModuleBudgets = Object.freeze([
  Object.freeze({ path: "features/travellers/services/draft-passport-identity.ts", baselineLines: 10, maximumLines: 10, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/travellers/api/draft-image-lifecycle.api.ts", baselineLines: 13, maximumLines: 15, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/travellers/api/draft-upload-body.ts", baselineLines: 6, maximumLines: 10, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/travellers/api/draft.types.ts", baselineLines: 24, maximumLines: 25, baselineMaxFunctionComplexity: 0, maximumFunctionComplexity: 0 }),
  Object.freeze({ path: "features/travellers/hooks/use-draft-image-lifecycle.ts", baselineLines: 49, maximumLines: 50, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/travellers/hooks/use-draft-initialization.ts", baselineLines: 25, maximumLines: 25, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/travellers/hooks/use-draft-polling.ts", baselineLines: 23, maximumLines: 25, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/travellers/services/draft-check-state.ts", baselineLines: 5, maximumLines: 10, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/travellers/services/draft-field-value.ts", baselineLines: 8, maximumLines: 10, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/travellers/services/draft-file-identity.ts", baselineLines: 17, maximumLines: 20, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/travellers/services/draft-upload-operation.ts", baselineLines: 32, maximumLines: 35, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "features/upload/api/fresh-draft.types.ts", baselineLines: 12, maximumLines: 15, baselineMaxFunctionComplexity: 0, maximumFunctionComplexity: 0 }),
  Object.freeze({ path: "features/upload/components/document-processing-frame.tsx", baselineLines: 12, maximumLines: 15, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/upload/components/draft-document-card.tsx", baselineLines: 35, maximumLines: 35, baselineMaxFunctionComplexity: 18, maximumFunctionComplexity: 18 }),
  Object.freeze({ path: "features/upload/components/fresh-submission-footer.tsx", baselineLines: 15, maximumLines: 15, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "features/upload/components/review-details-column.tsx", baselineLines: 22, maximumLines: 25, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/upload/components/selected-document-preview.tsx", baselineLines: 19, maximumLines: 20, baselineMaxFunctionComplexity: 4, maximumFunctionComplexity: 4 }),
  Object.freeze({ path: "features/upload/hooks/use-selected-document-uploads.ts", baselineLines: 46, maximumLines: 50, baselineMaxFunctionComplexity: 11, maximumFunctionComplexity: 11 }),
  Object.freeze({ path: "features/upload/services/document-preview-order.ts", baselineLines: 15, maximumLines: 20, baselineMaxFunctionComplexity: 6, maximumFunctionComplexity: 6 }),
  Object.freeze({ path: "features/upload/services/fresh-document-validation.ts", baselineLines: 23, maximumLines: 25, baselineMaxFunctionComplexity: 13, maximumFunctionComplexity: 13 }),
]);

describe("draft and document module budgets", () => {
  it.each(draftModuleBudgets)("keeps $path within its reviewed size and complexity", (budget) => {
    const [result] = evaluateBudgets([budget]);
    expect(result.actualLines).toBeLessThanOrEqual(budget.maximumLines);
    expect(result.actualMaxFunctionComplexity).toBeLessThanOrEqual(budget.maximumFunctionComplexity);
    expect(result.withinBudget).toBe(true);
  });
});
