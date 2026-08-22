import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

// Baselines capture the reviewed pre-decomposition state. Small ceilings allow
// a bug fix without normalizing continued growth; a cohesive extraction should
// lower the baseline and ceiling in the same review.
export const frontendModuleBudgets = Object.freeze([
  Object.freeze({ path: "features/passports/components/passport-group-detail.tsx", baselineLines: 2_184, maximumLines: 2_210, baselineMaxFunctionComplexity: 131, maximumFunctionComplexity: 134 }),
  Object.freeze({ path: "features/email-integrations/components/message-activity-page.tsx", baselineLines: 2_073, maximumLines: 2_100, baselineMaxFunctionComplexity: 52, maximumFunctionComplexity: 55 }),
  Object.freeze({ path: "features/upload/components/upload-flow.tsx", baselineLines: 1_986, maximumLines: 2_010, baselineMaxFunctionComplexity: 66, maximumFunctionComplexity: 69 }),
  Object.freeze({ path: "features/passports/components/group-whatsapp-broadcast-panel.tsx", baselineLines: 1_733, maximumLines: 1_760, baselineMaxFunctionComplexity: 58, maximumFunctionComplexity: 61 }),
  Object.freeze({ path: "features/passports/components/passport-detail.tsx", baselineLines: 1_577, maximumLines: 1_600, baselineMaxFunctionComplexity: 54, maximumFunctionComplexity: 57 }),
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
