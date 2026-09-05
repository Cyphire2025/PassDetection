import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import * as bindings from "./mediapipe-csp-bindings.mjs";
import { Ec, settleMediapipeInitialization } from "./mediapipe-main-loader-bindings.mjs";

export const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
export const upstreamVersion = "0.4.1646425229";
export const sourceHashes = {
  "face_detection_solution_wasm_bin.js": "ef3dd51abb4309f8428d32b23a9e89d4105e2eb83444620ae56599a4d2728433",
  "face_detection_solution_simd_wasm_bin.js": "ac6721ba5e4ddba4b145116e5012a0e2536c95cd814230e7095fbda78c4e46b7",
};
export const mainSourceHashes = {
  "face_detection.js": "464efd192f197f1000ab60bedde235f349b8ee2967e1443cc3a29cebf42cbce2",
};
export const unchangedHashes = {
  "face_detection_short.binarypb": "771c6b632d5ba58a41d3160abfd80185a1d18081f52bcefc5baec9f3d10aa8d9",
  "face_detection_short_range.tflite": "3bc182eb9f33925d9e58b5c8d59308a760f4adea8f282370e428c51212c26633",
  "face_detection_solution_wasm_bin.wasm": "7b69c41171c1cfedacc614c5dfdbb9df7e99356bf857d81de835e99414abd8d3",
  "face_detection_solution_simd_wasm_bin.wasm": "ed927313be5ead0002008a7bc18177ecd342c60fd75795e4611fb44e19c4745b",
};
export const sha256 = (value) => createHash("sha256").update(value).digest("hex");
// Git may check generated assets and binding sources out as CRLF on Windows.
// Normalize generated text only; upstream package hashes remain byte-exact.
export const normalizeGeneratedAsset = (source) => source.replace(/\r\n/g, "\n");

export function parseAsset(source) {
  const tree = ts.createSourceFile("mediapipe.js", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  if (tree.parseDiagnostics.length) throw new Error("MediaPipe asset contains invalid JavaScript");
  return tree;
}

export function findFunction(source, name) {
  const tree = parseAsset(source);
  const matches = [];
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === name) matches.push(node);
    ts.forEachChild(node, visit);
  }
  visit(tree);
  if (matches.length !== 1) throw new Error(`Expected exactly one ${name}, found ${matches.length}`);
  return { start: matches[0].getStart(tree), end: matches[0].end, source: matches[0].getText(tree) };
}

export function assertNoStringCodeGeneration(source) {
  const tree = parseAsset(source);
  function visit(node) {
    if ((ts.isCallExpression(node) || ts.isNewExpression(node)) && ts.isIdentifier(node.expression)) {
      if (["Function", "eval"].includes(node.expression.text)
        || (node.expression.text === "new_" && node.arguments?.[0]?.getText(tree) === "Function")) {
        throw new Error(`String code generation remains: ${node.getText(tree)}`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
}

export function patchAsset(source, filename) {
  if (sha256(source) !== sourceHashes[filename]) {
    throw new Error(`Unrecognized upstream asset ${filename}. Review any new release before updating pins.`);
  }
  const replacements = Object.entries(bindings).map(([name, fn]) => ({ ...findFunction(source, name), replacement: normalizeGeneratedAsset(fn.toString()) }));
  let patched = source;
  for (const replacement of replacements.sort((a, b) => b.start - a.start)) {
    patched = patched.slice(0, replacement.start) + replacement.replacement + patched.slice(replacement.end);
  }
  assertNoStringCodeGeneration(patched);
  return patched;
}

export function patchMainAsset(source, filename) {
  if (sha256(source) !== mainSourceHashes[filename]) {
    throw new Error(`Unrecognized upstream asset ${filename}. Review any new release before updating pins.`);
  }
  const initializer = findFunction(source, "Hc");
  if (initializer.source.split("Promise.all(").length !== 4) {
    throw new Error("Expected three concurrent MediaPipe initialization groups");
  }
  const fetcher = findFunction(source, "Ic");
  const originalFetch = "return g.arrayBuffer()";
  if (fetcher.source.split(originalFetch).length !== 2) throw new Error("Unexpected MediaPipe asset fetcher");
  const replacements = [
    {
      ...initializer,
      replacement: normalizeGeneratedAsset(settleMediapipeInitialization.toString()) + "\n"
        + initializer.source.replaceAll("Promise.all(", "settleMediapipeInitialization("),
    },
    { ...findFunction(source, "Ec"), replacement: normalizeGeneratedAsset(Ec.toString()) },
    {
      ...fetcher,
      replacement: fetcher.source.replace(originalFetch,
        'if(!g.ok)throw new Error("Unable to load face detection asset (HTTP "+g.status+"): "+c);return g.arrayBuffer()'),
    },
  ];
  let patched = source;
  for (const replacement of replacements.sort((a, b) => b.start - a.start)) {
    patched = patched.slice(0, replacement.start) + replacement.replacement + patched.slice(replacement.end);
  }
  assertNoStringCodeGeneration(patched);
  return patched;
}

export async function verifyOrWrite({ write = false } = {}) {
  const upstream = path.join(frontendRoot, "node_modules/@mediapipe/face_detection");
  const target = path.join(frontendRoot, "public/mediapipe/face_detection");
  const pkg = JSON.parse(await readFile(path.join(upstream, "package.json"), "utf8"));
  if (pkg.version !== upstreamVersion) throw new Error(`Unexpected MediaPipe version ${pkg.version}`);
  for (const [filename, expected] of Object.entries(unchangedHashes)) {
    for (const directory of [upstream, target]) {
      if (sha256(await readFile(path.join(directory, filename))) !== expected) {
        throw new Error(`Unchanged model/WASM asset differs: ${path.join(directory, filename)}`);
      }
    }
  }
  for (const filename of Object.keys({ ...sourceHashes, ...mainSourceHashes })) {
    const patch = filename in mainSourceHashes ? patchMainAsset : patchAsset;
    const patched = patch(await readFile(path.join(upstream, filename), "utf8"), filename);
    if (write) await writeFile(path.join(target, filename), patched);
    else if (normalizeGeneratedAsset(await readFile(path.join(target, filename), "utf8")) !== patched) {
      throw new Error(`${filename} needs regeneration: node scripts/patch-mediapipe-csp.mjs --write`);
    }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.slice(2).some((arg) => !["--write", "--check"].includes(arg))) throw new Error("Use --write or --check");
  await verifyOrWrite({ write: process.argv.includes("--write") });
  console.log("MediaPipe CSP bindings verified; detection graph, model, and WASM are unchanged.");
}
