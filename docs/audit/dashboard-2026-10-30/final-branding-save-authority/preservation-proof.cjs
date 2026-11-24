const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const ts = require('../../frontend/node_modules/typescript');
const root = path.resolve(__dirname, '../..');
const audit = path.join(root, 'docs/audit/dashboard-2026-10-30/final-branding-save-authority');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const hash = p => crypto.createHash('sha256').update(fs.readFileSync(path.join(root, p))).digest('hex');
const parse = s => ts.createSourceFile('source.tsx', s, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const printer = ts.createPrinter({ removeComments: true, newLine: ts.NewLineKind.LineFeed });
const normalized = s => printer.printFile(parse(s));
const find = (source, predicate) => {
  const found = [];
  function visit(node) { if (predicate(node)) found.push(node); ts.forEachChild(node, visit); }
  visit(source);
  return found;
};
const printed = (node, source) => printer.printNode(ts.EmitHint.Unspecified, node, source);
const dialog = 'frontend/features/branding/components/group-image-dialog.tsx';
const api = 'frontend/features/branding/api/branding-images.api.ts';
const geometry = 'frontend/features/branding/components/group-image-dialog.test.tsx';
const before = '.tmp/branding-save-authority/before-source/';
const oldDialog = parse(read(before + dialog));
const newDialog = parse(read(dialog));
const functionNamed = (s, name) => find(s, n => ts.isFunctionDeclaration(n) && n.name?.text === name)[0];
const oldFunction = functionNamed(oldDialog, 'GroupImageDialog');
const newFunction = functionNamed(newDialog, 'GroupImageDialog');
const oldReturn = oldFunction.body.statements.find(ts.isReturnStatement);
const newReturn = newFunction.body.statements.find(ts.isReturnStatement);
const results = {
  dialog_return_jsx_ast_identical: printed(oldReturn, oldDialog) === printed(newReturn, newDialog),
  dialog_public_parameters_ast_identical: oldFunction.parameters.map(n => printed(n, oldDialog)).join('\n') === newFunction.parameters.map(n => printed(n, newDialog)).join('\n'),
};
for (const name of ['source', 'image']) {
  const get = s => find(s, n => ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === name).map(n => printed(n, s));
  results[`dialog_${name}_crop_expression_ast_identical`] = JSON.stringify(get(oldDialog)) === JSON.stringify(get(newDialog));
}
let inverseApi = read(api)
  .replace('assertRequestOwner, capturePrivateOperationOwner, ownerBoundRequestConfig, type OwnerBoundRequestConfig', 'assertRequestOwner, capturePrivateOperationOwner')
  .replace('expectedOwnerUserId?: string,\n  operationOptions?: Pick<OwnerBoundRequestConfig, "expectedAuthorityKey" | "signal">)', 'expectedOwnerUserId?: string)')
  .replace(': { ...ownerBoundRequestConfig(expectedOwnerUserId), ...operationOptions };', ': { expectedOwnerUserId };');
results.whole_api_ast_identical_after_explicit_authority_metadata_inverse = normalized(inverseApi) === normalized(read(before + api));
const oldGeometry = read('docs/audit/dashboard-2026-10-30/final-banner-target-frame/current-source-snapshots/' + geometry);
let inverseGeometry = read(geometry)
  .replace('import { useAuthStore } from "@/stores/auth.store";\nimport type { User } from "@/types";\n', '')
  .replace('  useAuthStore.setState({ user: { id: "branding-test-actor", role: "agency_admin", agency_id: "branding-test-agency" } as User });\n', '')
  .replace('afterEach(() => { vi.unstubAllGlobals(); useAuthStore.setState({ user: null }); });', 'afterEach(() => vi.unstubAllGlobals());')
  .replace('"/api/group-banner?v=original", "branding-test-actor", {\n      expectedAuthorityKey: JSON.stringify(["branding-test-actor", "agency_admin", "branding-test-agency"]), signal: expect.any(AbortSignal),\n    });', '"/api/group-banner?v=original");');
results.whole_geometry_test_ast_identical_after_explicit_fixture_and_expected_config_inverse = normalized(inverseGeometry) === normalized(oldGeometry);
if (Object.values(results).some(value => value !== true)) throw new Error(JSON.stringify(results));
fs.writeFileSync(path.join(audit, 'preservation-proof.json'), JSON.stringify({
  status: 'All bounded preservation comparisons passed; authority and lifetime guards are deliberate behavioral changes, not mechanical equivalence.',
  tool: 'Pinned project TypeScript parser/printer; comments and formatting excluded.',
  results,
  source_fence: Object.fromEntries([dialog, api, geometry, before + dialog, before + api].map(p => [p, hash(p)])),
  scope: [
    'Dialog return JSX, public parameters, crop input expressions remain identical. Save orchestration and controller cleanup intentionally changed.',
    'Whole API AST matches the original after only the explicit optional config/import/owner-freeze inverse. URL, params, FormData order, timeout, version, result, cache function and exported types therefore retain their original AST.',
    'All geometry test declarations/assertions retained after only synthetic auth setup/cleanup and the strengthened API config expectation inverse.',
    'Optional seventh API parameter changes reflected JavaScript function length; published positional default and six-argument calls remain accepted and tested. No claim of identical function metadata.'
  ]
}, null, 2) + '\n');
console.log(JSON.stringify(results));
