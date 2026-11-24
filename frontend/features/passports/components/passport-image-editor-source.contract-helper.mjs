import { readFileSync } from "node:fs";

const editorFiles = [
  "./passport-image-crop-editor.tsx",
  "./passport-image-library-panel.tsx",
  "./visa-ai-image-panel.tsx",
  "../hooks/use-passport-image-crop-editor.ts",
  "../hooks/use-passport-image-editor-source.ts",
  "../hooks/use-passport-image-editor-draft.ts",
  "../hooks/use-passport-image-crop-controls.ts",
  "../hooks/use-passport-image-editor-actions.ts",
  "../hooks/use-visa-ai-image-generation.ts",
  "../utils/passport-image-editor-state.ts",
  "../utils/passport-image-editor-preview.ts",
  "../services/visa-ai-generation-polling.ts",
];

export function readPassportImageEditorSource() {
  return editorFiles.map((file) => readFileSync(new URL(file, import.meta.url), "utf8")).join("\n");
}
