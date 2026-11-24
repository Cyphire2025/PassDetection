import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { countPhysicalLines, maxFunctionCyclomaticComplexity, frontendModuleBudgets } from "../../frontend/scripts/verify-frontend-module-budgets.mjs";
const root = resolve(import.meta.dirname, "../..");
const paths = ["features/branding/components/group-banner.tsx", "features/branding/components/group-banner-action.tsx", "features/branding/components/group-image-dialog.tsx", "features/branding/components/group-banner-frame.ts", "features/branding/components/use-group-image-aspect.ts", "features/branding/api/branding-images.api.ts"];
const measurements = paths.map(path => {
 const bytes = readFileSync(resolve(root, "frontend", path)); const source = bytes.toString("utf8");
 return { path, sha256: createHash("sha256").update(bytes).digest("hex"), physicalLines: countPhysicalLines(source), maximumFunctionComplexity: maxFunctionCyclomaticComplexity(source,path), existingBudget: frontendModuleBudgets.find(row=>row.path===path)??null };
});
const newNormalRows = measurements.map(row=>({path:row.path,baselineLines:row.physicalLines,maximumLines:Math.ceil(row.physicalLines/10)*10,baselineMaxFunctionComplexity:row.maximumFunctionComplexity,maximumFunctionComplexity:row.maximumFunctionComplexity+1}));
const result={status:"Additive measured candidate only; parent owns shared gates",existingNormalRows:frontendModuleBudgets.length,measurements,newNormalRows,newCriticalRows:[],constraints:"No old cap/floor changes; no existing branding owner rows/critical profile found. Public save/crop/URL contract unchanged."};
writeFileSync(resolve(root,".tmp/branding-save-authority/quality-budget-candidates.json"),JSON.stringify(result,null,2)+"\n");
process.stdout.write(JSON.stringify(result,null,2));
