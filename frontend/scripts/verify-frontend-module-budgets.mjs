import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

// Baselines capture the reviewed pre-decomposition state. Small ceilings allow
// a bug fix without normalizing continued growth; a cohesive extraction should
// lower the baseline and ceiling in the same review.
export const frontendModuleBudgets = Object.freeze([
  Object.freeze({ path: "features/travellers/hooks/use-draft-autosave.ts", baselineLines: 16, maximumLines: 16, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/travellers/components/returning-collection.tsx", baselineLines: 23, maximumLines: 25, baselineMaxFunctionComplexity: 6, maximumFunctionComplexity: 6 }),
  Object.freeze({ path: "features/upload/hooks/use-draft-document-upload.ts", baselineLines: 28, maximumLines: 30, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "features/travellers/services/draft-document-requirements.ts", baselineLines: 20, maximumLines: 20, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/upload/services/draft-input-contract.ts", baselineLines: 11, maximumLines: 15, baselineMaxFunctionComplexity: 0, maximumFunctionComplexity: 0 }),
  Object.freeze({ path: "features/companies/hooks/use-company-document-preview.ts", baselineLines: 39, maximumLines: 40, baselineMaxFunctionComplexity: 10, maximumFunctionComplexity: 10 }),
  Object.freeze({ path: "features/upload/components/traveller-portal.tsx", baselineLines: 55, maximumLines: 55, baselineMaxFunctionComplexity: 9, maximumFunctionComplexity: 9 }),
  Object.freeze({ path: "features/upload/components/traveller-shell.tsx", baselineLines: 12, maximumLines: 15, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/travellers/api/returning-draft.api.ts", baselineLines: 38, maximumLines: 40, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/travellers/hooks/use-returning-draft.ts", baselineLines: 143, maximumLines: 145, baselineMaxFunctionComplexity: 14, maximumFunctionComplexity: 14 }),
  Object.freeze({ path: "features/travellers/components/returning-challenge.tsx", baselineLines: 31, maximumLines: 35, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/travellers/components/returning-draft-images.tsx", baselineLines: 26, maximumLines: 30, baselineMaxFunctionComplexity: 7, maximumFunctionComplexity: 7 }),
  Object.freeze({ path: "features/travellers/components/returning-phone.tsx", baselineLines: 36, maximumLines: 40, baselineMaxFunctionComplexity: 11, maximumFunctionComplexity: 11 }),
  Object.freeze({ path: "features/travellers/components/returning-resume.tsx", baselineLines: 23, maximumLines: 25, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/travellers/components/traveller-document.tsx", baselineLines: 45, maximumLines: 45, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "features/travellers/services/draft-readiness.ts", baselineLines: 21, maximumLines: 25, baselineMaxFunctionComplexity: 4, maximumFunctionComplexity: 4 }),
  Object.freeze({ path: "features/travellers/services/draft-reconcile.ts", baselineLines: 15, maximumLines: 15, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "features/travellers/services/private-preview-queue.ts", baselineLines: 21, maximumLines: 25, baselineMaxFunctionComplexity: 4, maximumFunctionComplexity: 4 }),
  Object.freeze({ path: "features/upload/hooks/use-fresh-draft.ts", baselineLines: 124, maximumLines: 125, baselineMaxFunctionComplexity: 14, maximumFunctionComplexity: 14 }),
  Object.freeze({ path: "features/upload/api/fresh-draft.api.ts", baselineLines: 33, maximumLines: 35, baselineMaxFunctionComplexity: 1, maximumFunctionComplexity: 1 }),
  Object.freeze({ path: "features/travellers/services/draft-resume.ts", baselineLines: 52, maximumLines: 55, baselineMaxFunctionComplexity: 9, maximumFunctionComplexity: 9 }),
  Object.freeze({ path: "features/upload/components/fresh-contact.tsx", baselineLines: 49, maximumLines: 50, baselineMaxFunctionComplexity: 23, maximumFunctionComplexity: 23 }),
  Object.freeze({ path: "features/upload/components/fresh-document-preview.tsx", baselineLines: 32, maximumLines: 35, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/upload/components/fresh-documents.tsx", baselineLines: 55, maximumLines: 55, baselineMaxFunctionComplexity: 14, maximumFunctionComplexity: 14 }),
  Object.freeze({ path: "features/upload/components/fresh-flow.tsx", baselineLines: 42, maximumLines: 45, baselineMaxFunctionComplexity: 10, maximumFunctionComplexity: 10 }),
  Object.freeze({ path: "features/upload/components/fresh-member-form.tsx", baselineLines: 58, maximumLines: 60, baselineMaxFunctionComplexity: 17, maximumFunctionComplexity: 17 }),
  Object.freeze({ path: "features/upload/components/fresh-member.tsx", baselineLines: 29, maximumLines: 30, baselineMaxFunctionComplexity: 7, maximumFunctionComplexity: 7 }),
  Object.freeze({ path: "features/upload/components/fresh-qualifier.tsx", baselineLines: 24, maximumLines: 25, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/upload/components/fresh-trip-fields.tsx", baselineLines: 20, maximumLines: 20, baselineMaxFunctionComplexity: 14, maximumFunctionComplexity: 14 }),
  Object.freeze({ path: "features/upload/services/fresh-draft-state.ts", baselineLines: 15, maximumLines: 15, baselineMaxFunctionComplexity: 7, maximumFunctionComplexity: 7 }),
  Object.freeze({ path: "features/upload/services/fresh-validation.ts", baselineLines: 31, maximumLines: 35, baselineMaxFunctionComplexity: 15, maximumFunctionComplexity: 15 }),
  Object.freeze({ path: "features/companies/utils/company-navigation.ts", baselineLines: 25, maximumLines: 30, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "features/companies/utils/company-index-status.ts", baselineLines: 6, maximumLines: 10, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/companies/components/company-people-results.tsx", baselineLines: 17, maximumLines: 25, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "features/companies/utils/company-search.ts", baselineLines: 8, maximumLines: 15, baselineMaxFunctionComplexity: 7, maximumFunctionComplexity: 7 }),
  Object.freeze({ path: "features/companies/hooks/use-company-view-state.ts", baselineLines: 21, maximumLines: 25, baselineMaxFunctionComplexity: 4, maximumFunctionComplexity: 4 }),
  Object.freeze({ path: "features/companies/hooks/use-company-people.ts", baselineLines: 38, maximumLines: 45, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "features/companies/components/company-view-tabs.tsx", baselineLines: 21, maximumLines: 25, baselineMaxFunctionComplexity: 6, maximumFunctionComplexity: 6 }),
  Object.freeze({ path: "features/companies/components/company-person-row.tsx", baselineLines: 14, maximumLines: 20, baselineMaxFunctionComplexity: 4, maximumFunctionComplexity: 4 }),
  Object.freeze({ path: "features/companies/components/company-people-toolbar.tsx", baselineLines: 17, maximumLines: 25, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/companies/components/company-person-details.tsx", baselineLines: 21, maximumLines: 30, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/companies/components/company-group-return-link.tsx", baselineLines: 15, maximumLines: 20, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/companies/components/company-person-documents.tsx", baselineLines: 35, maximumLines: 45, baselineMaxFunctionComplexity: 18, maximumFunctionComplexity: 18 }),
  Object.freeze({ path: "features/companies/components/company-original-documents.tsx", baselineLines: 20, maximumLines: 30, baselineMaxFunctionComplexity: 11, maximumFunctionComplexity: 11 }),
  // Company metadata/private-record and member-bound reuse boundaries reviewed 2026-10-14.
  Object.freeze({ path: "features/companies/components/company-all-data.tsx", baselineLines: 43, maximumLines: 50, baselineMaxFunctionComplexity: 28, maximumFunctionComplexity: 28 }),
  Object.freeze({ path: "features/companies/components/company-person-page.tsx", baselineLines: 56, maximumLines: 60, baselineMaxFunctionComplexity: 26, maximumFunctionComplexity: 26 }),
  Object.freeze({ path: "features/companies/components/company-person-editor.tsx", baselineLines: 49, maximumLines: 50, baselineMaxFunctionComplexity: 10, maximumFunctionComplexity: 10 }),
  Object.freeze({ path: "features/companies/components/company-document-upload.tsx", baselineLines: 64, maximumLines: 70, baselineMaxFunctionComplexity: 13, maximumFunctionComplexity: 13 }),
  Object.freeze({ path: "features/companies/components/company-document-preview.tsx", baselineLines: 17, maximumLines: 20, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/companies/components/company-data-exports.tsx", baselineLines: 50, maximumLines: 50, baselineMaxFunctionComplexity: 16, maximumFunctionComplexity: 16 }),
  Object.freeze({ path: "features/companies/components/company-settings.tsx", baselineLines: 50, maximumLines: 50, baselineMaxFunctionComplexity: 15, maximumFunctionComplexity: 15 }),
  Object.freeze({ path: "features/companies/components/company-match-queue.tsx", baselineLines: 32, maximumLines: 40, baselineMaxFunctionComplexity: 13, maximumFunctionComplexity: 13 }),
  Object.freeze({ path: "features/companies/hooks/use-company-session.ts", baselineLines: 14, maximumLines: 20, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 2 }),
  Object.freeze({ path: "features/companies/hooks/use-companies.ts", baselineLines: 75, maximumLines: 80, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/upload/hooks/use-returning-family.tsx", baselineLines: 48, maximumLines: 50, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 8 }),
  Object.freeze({ path: "components/ui/modal-focus-return.tsx", baselineLines: 32, maximumLines: 40, baselineMaxFunctionComplexity: 4, maximumFunctionComplexity: 6 }),
  Object.freeze({ path: "features/passports/components/group-whatsapp-dialogs.tsx", baselineLines: 421, maximumLines: 440, baselineMaxFunctionComplexity: 14, maximumFunctionComplexity: 16 }),
  Object.freeze({ path: "features/passports/components/group-whatsapp-tracking-table.tsx", baselineLines: 417, maximumLines: 440, baselineMaxFunctionComplexity: 37, maximumFunctionComplexity: 39 }),
  Object.freeze({ path: "features/passports/components/group-whatsapp-tracking-model.ts", baselineLines: 163, maximumLines: 175, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 10 }),
  Object.freeze({ path: "features/passports/components/use-passport-detail-navigation.ts", baselineLines: 116, maximumLines: 130, baselineMaxFunctionComplexity: 24, maximumFunctionComplexity: 26 }),
  Object.freeze({ path: "features/upload/services/saved-passport-extraction.ts", baselineLines: 72, maximumLines: 90, baselineMaxFunctionComplexity: 17, maximumFunctionComplexity: 19 }),
  Object.freeze({ path: "lib/observability/render-errors.ts", baselineLines: 64, maximumLines: 80, baselineMaxFunctionComplexity: 4, maximumFunctionComplexity: 6 }),
  Object.freeze({ path: "components/ui/modal-keyboard-boundary.ts", baselineLines: 119, maximumLines: 135, baselineMaxFunctionComplexity: 15, maximumFunctionComplexity: 17 }),
  Object.freeze({ path: "features/passports/components/passport-group-bindings.tsx", baselineLines: 101, maximumLines: 125, baselineMaxFunctionComplexity: 1, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/passports/components/passport-group-detail.tsx", baselineLines: 22, maximumLines: 50, baselineMaxFunctionComplexity: 1, maximumFunctionComplexity: 3 }),
  Object.freeze({ path: "features/passports/components/passport-group-dialogs.tsx", baselineLines: 314, maximumLines: 325, baselineMaxFunctionComplexity: 10, maximumFunctionComplexity: 12 }),
  Object.freeze({ path: "features/passports/components/passport-group-header-panel.tsx", baselineLines: 294, maximumLines: 325, baselineMaxFunctionComplexity: 20, maximumFunctionComplexity: 22 }),
  Object.freeze({ path: "features/passports/components/passport-group-import-panel.tsx", baselineLines: 171, maximumLines: 200, baselineMaxFunctionComplexity: 7, maximumFunctionComplexity: 9 }),
  Object.freeze({ path: "features/passports/components/passport-group-model.tsx", baselineLines: 586, maximumLines: 600, baselineMaxFunctionComplexity: 26, maximumFunctionComplexity: 28 }),
  Object.freeze({ path: "features/passports/components/passport-group-overview-panel.tsx", baselineLines: 340, maximumLines: 350, baselineMaxFunctionComplexity: 46, maximumFunctionComplexity: 48 }),
  Object.freeze({ path: "features/passports/components/passport-group-roster-panel.tsx", baselineLines: 340, maximumLines: 350, baselineMaxFunctionComplexity: 15, maximumFunctionComplexity: 17 }),
  Object.freeze({ path: "features/passports/components/passport-group-selection-toolbar.tsx", baselineLines: 350, maximumLines: 375, baselineMaxFunctionComplexity: 18, maximumFunctionComplexity: 20 }),
  Object.freeze({ path: "features/passports/components/use-passport-group-controller.tsx", baselineLines: 698, maximumLines: 725, baselineMaxFunctionComplexity: 23, maximumFunctionComplexity: 25 }),
  Object.freeze({ path: "features/email-integrations/components/message-activity-model.ts", baselineLines: 172, maximumLines: 200, baselineMaxFunctionComplexity: 9, maximumFunctionComplexity: 11 }),
  Object.freeze({ path: "features/email-integrations/components/message-activity-page.tsx", baselineLines: 315, maximumLines: 325, baselineMaxFunctionComplexity: 21, maximumFunctionComplexity: 23 }),
  Object.freeze({ path: "features/email-integrations/components/message-deadline-decisions.tsx", baselineLines: 141, maximumLines: 175, baselineMaxFunctionComplexity: 10, maximumFunctionComplexity: 12 }),
  Object.freeze({ path: "features/email-integrations/components/message-draft-editor.tsx", baselineLines: 260, maximumLines: 275, baselineMaxFunctionComplexity: 16, maximumFunctionComplexity: 18 }),
  Object.freeze({ path: "features/email-integrations/components/message-intelligence-brief.tsx", baselineLines: 384, maximumLines: 400, baselineMaxFunctionComplexity: 23, maximumFunctionComplexity: 25 }),
  Object.freeze({ path: "features/email-integrations/components/message-intelligence-feedback.tsx", baselineLines: 521, maximumLines: 550, baselineMaxFunctionComplexity: 45, maximumFunctionComplexity: 47 }),
  Object.freeze({ path: "features/email-integrations/components/message-proposal-decisions.tsx", baselineLines: 143, maximumLines: 175, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 10 }),
  Object.freeze({ path: "features/email-integrations/components/use-message-feedback-controller.ts", baselineLines: 276, maximumLines: 300, baselineMaxFunctionComplexity: 8, maximumFunctionComplexity: 10 }),
  Object.freeze({ path: "features/settings/components/dashboard-settings-page.tsx", baselineLines: 306, maximumLines: 325, baselineMaxFunctionComplexity: 5, maximumFunctionComplexity: 7 }),
  Object.freeze({ path: "features/settings/components/platform-settings-panel.tsx", baselineLines: 642, maximumLines: 675, baselineMaxFunctionComplexity: 24, maximumFunctionComplexity: 26 }),
  Object.freeze({ path: "lib/hooks/use-live-history-feed.ts", baselineLines: 99, maximumLines: 125, baselineMaxFunctionComplexity: 10, maximumFunctionComplexity: 12 }),
  Object.freeze({ path: "features/upload/components/upload-flow.tsx", baselineLines: 746, maximumLines: 765, baselineMaxFunctionComplexity: 50, maximumFunctionComplexity: 50 }),
  Object.freeze({ path: "features/upload/components/upload-review-panels.tsx", baselineLines: 291, maximumLines: 310, baselineMaxFunctionComplexity: 15, maximumFunctionComplexity: 17 }),
  Object.freeze({ path: "features/upload/hooks/use-upload-documents.ts", baselineLines: 445, maximumLines: 460, baselineMaxFunctionComplexity: 39, maximumFunctionComplexity: 39 }),
  Object.freeze({ path: "features/upload/hooks/use-upload-submission.ts", baselineLines: 169, maximumLines: 185, baselineMaxFunctionComplexity: 26, maximumFunctionComplexity: 26 }),
  Object.freeze({ path: "features/upload/hooks/use-upload-operation.ts", baselineLines: 43, maximumLines: 55, baselineMaxFunctionComplexity: 3, maximumFunctionComplexity: 5 }),
  Object.freeze({ path: "features/upload/hooks/use-upload-family.ts", baselineLines: 23, maximumLines: 35, baselineMaxFunctionComplexity: 2, maximumFunctionComplexity: 4 }),
  Object.freeze({ path: "features/upload/services/upload-operation-state.ts", baselineLines: 19, maximumLines: 30, baselineMaxFunctionComplexity: 4, maximumFunctionComplexity: 6 }),
  Object.freeze({ path: "features/upload/services/family-upload-state.ts", baselineLines: 39, maximumLines: 50, baselineMaxFunctionComplexity: 12, maximumFunctionComplexity: 14 }),
  Object.freeze({ path: "features/upload/services/review-submission-validation.ts", baselineLines: 108, maximumLines: 120, baselineMaxFunctionComplexity: 17, maximumFunctionComplexity: 19 }),
  Object.freeze({ path: "features/passports/components/group-whatsapp-broadcast-panel.tsx", baselineLines: 691, maximumLines: 715, baselineMaxFunctionComplexity: 59, maximumFunctionComplexity: 59 }),
  Object.freeze({ path: "features/passports/components/passport-detail.tsx", baselineLines: 1411, maximumLines: 1430, baselineMaxFunctionComplexity: 40, maximumFunctionComplexity: 40 }),
]);

export function countPhysicalLines(source) {
  const normalized = source.replace(/\r\n?/g, "\n");
  if (normalized.length === 0) return 0;
  const lines = normalized.split("\n");
  return lines.at(-1) === "" ? lines.length - 1 : lines.length;
}

const COMPLEXITY_BINARY_OPERATORS = new Set([
  ts.SyntaxKind.AmpersandAmpersandToken,
  ts.SyntaxKind.BarBarToken,
  ts.SyntaxKind.QuestionQuestionToken,
]);

function isFunctionLike(node) {
  return ts.isArrowFunction(node)
    || ts.isFunctionDeclaration(node)
    || ts.isFunctionExpression(node)
    || ts.isMethodDeclaration(node)
    || ts.isGetAccessorDeclaration(node)
    || ts.isSetAccessorDeclaration(node)
    || ts.isConstructorDeclaration(node);
}

/**
 * Computes the highest cyclomatic complexity of any function in a TS/TSX
 * module. Nested functions are measured independently, so extracting a hook or
 * dialog genuinely lowers the parent budget instead of merely moving branches
 * under an inline callback.
 */
export function maxFunctionCyclomaticComplexity(source, path = "module.tsx") {
  const sourceFile = ts.createSourceFile(
    path,
    source,
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  let maximum = 0;

  const measureFunction = (functionNode) => {
    let complexity = 1;
    const visitBody = (node) => {
      if (node !== functionNode && isFunctionLike(node)) return;
      if (
        ts.isIfStatement(node)
        || ts.isForStatement(node)
        || ts.isForInStatement(node)
        || ts.isForOfStatement(node)
        || ts.isWhileStatement(node)
        || ts.isDoStatement(node)
        || ts.isConditionalExpression(node)
        || ts.isCatchClause(node)
        || (ts.isCaseClause(node) && node.expression !== undefined)
        || (ts.isBinaryExpression(node) && COMPLEXITY_BINARY_OPERATORS.has(node.operatorToken.kind))
      ) {
        complexity += 1;
      }
      ts.forEachChild(node, visitBody);
    };
    if (functionNode.body) visitBody(functionNode.body);
    maximum = Math.max(maximum, complexity);
  };

  const visitFunctions = (node) => {
    if (isFunctionLike(node)) measureFunction(node);
    ts.forEachChild(node, visitFunctions);
  };
  visitFunctions(sourceFile);
  return maximum;
}

export function evaluateFrontendModuleBudgets(
  budgets = frontendModuleBudgets,
  readSource = (relativePath) => readFileSync(resolve(frontendRoot, relativePath), "utf8"),
) {
  return budgets.map((budget) => {
    const source = readSource(budget.path);
    const actualLines = countPhysicalLines(source);
    const actualMaxFunctionComplexity = maxFunctionCyclomaticComplexity(source, budget.path);
    return Object.freeze({
      ...budget,
      actualLines,
      actualMaxFunctionComplexity,
      withinBudget: actualLines <= budget.maximumLines
        && actualMaxFunctionComplexity <= budget.maximumFunctionComplexity,
    });
  });
}

function run() {
  const results = evaluateFrontendModuleBudgets();
  const failures = results.filter((result) => !result.withinBudget);
  if (failures.length > 0) {
    for (const failure of failures) {
      if (failure.actualLines > failure.maximumLines) {
        console.error(
          `${failure.path}: ${failure.actualLines} lines exceeds ${failure.maximumLines} `
          + `(reviewed baseline ${failure.baselineLines}). Extract a cohesive module instead of increasing the budget.`,
        );
      }
      if (failure.actualMaxFunctionComplexity > failure.maximumFunctionComplexity) {
        console.error(
          `${failure.path}: maximum function complexity ${failure.actualMaxFunctionComplexity} exceeds `
          + `${failure.maximumFunctionComplexity} (reviewed baseline ${failure.baselineMaxFunctionComplexity}). `
          + "Extract a cohesive hook, handler, or component instead of increasing the budget.",
        );
      }
    }
    process.exitCode = 1;
    return;
  }
  console.log(`Frontend size and complexity budgets passed (${results.length} high-risk modules checked).`);
  for (const result of results) {
    console.log(`${result.path}: ${result.actualLines} lines; max function complexity ${result.actualMaxFunctionComplexity}.`);
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) run();
