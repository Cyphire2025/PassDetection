import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";

// A fresh process prevents cached Zod config/eval detection from hiding an early
// probe. The fixture blocks Function exactly as the production CSP does.
function validateWithoutEval(module: string) {
  const code = `
    let attempts = 0;
    const deny = () => { attempts++; throw new EvalError("CSP fixture"); };
    globalThis.Function = new Proxy(globalThis.Function, { apply: deny, construct: deny });
    const { z } = await import(process.argv[1]);
    const schema = z.object({ label: z.string().trim().min(1), count: z.number().int().positive().default(1) }).strict();
    const valid = { label: " sample " };
    console.log(JSON.stringify({
      parsed: schema.parse(valid), asyncParsed: await schema.parseAsync(valid),
      invalid: schema.safeParse({ label: " ", count: 0 }).success,
      extra: schema.safeParse({ ...valid, unexpected: true }).success,
      attempts,
    }));
  `;
  return JSON.parse(execFileSync(process.execPath, ["--input-type=module", "-e", code, module], { encoding: "utf8", timeout: 10_000 }));
}

describe("CSP-compatible schema validation", () => {
  it("detects the original caught Zod probe in a fresh environment", () => {
    expect(validateWithoutEval("zod").attempts).toBe(1);
  });

  it("never attempts eval while preserving strict, transformed, default and async validation", () => {
    expect(validateWithoutEval(pathToFileURL(resolve("lib/zod.ts")).href)).toEqual({
      parsed: { label: "sample", count: 1 }, asyncParsed: { label: "sample", count: 1 },
      invalid: false, extra: false, attempts: 0,
    });
  });
});
