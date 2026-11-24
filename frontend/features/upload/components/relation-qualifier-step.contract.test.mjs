import assert from "node:assert/strict";
import test from "node:test";
import { currentUploadSources as source, readUploadSource } from "./current-upload-source.contract-helper.mjs";

test("each active private member saves its own validated qualifier selection", () => {
  const facade = readUploadSource("./fresh-qualifier.tsx");
  const qualifier = readUploadSource("./fresh-qualifier-editor.tsx");
  const selection = readUploadSource("../hooks/use-qualifier-selection-editor.ts");
  assert.match(facade, /import \{ FreshQualifierEditor \} from "\.\/fresh-qualifier-editor"/);
  assert.match(facade, /return <FreshQualifierEditor key=\{`\$\{props\.group\.token\}:\$\{proof\}`\} \{\.\.\.props\} \/>/);
  assert.match(qualifier, /import \{ useQualifierSelectionEditor \} from "\.\.\/hooks\/use-qualifier-selection-editor"/);
  assert.match(qualifier, /useQualifierSelectionEditor\(group\.token, savedToken\)/);
  assert.match(selection, /export function useQualifierSelectionEditor\(/);
  assert.match(selection, /getQualifierSelection\(groupToken, selectionToken, controller\.signal\)/);
  assert.match(qualifier, /import \{ buildQualifierSelectionRequest \} from "\.\.\/services\/relation-qualifier"/);
  assert.match(qualifier, /buildQualifierSelectionRequest\(/);
  assert.match(qualifier, /if \(!choice\) return/);
  assert.match(qualifier, /state\.serialized\(async signal =>/);
  assert.match(qualifier, /state\.api\.qualifier\(choice, signal\)/);
  assert.match(qualifier, /signal\.throwIfAborted\(\)/);
  assert.match(qualifier, /state\.collection\(\{ qualifier_selection_token: result\.selection_token \}\)/);
  assert.match(source.validation, /!payload\.collection\?\.qualifier_selection_token/);
  assert.match(source.fresh, /key=\{resume\.members\[resume\.active\]\.sessionId\}/);
});
