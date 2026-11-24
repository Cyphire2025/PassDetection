import assert from "node:assert/strict";
import { EventEmitter, once } from "node:events";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { test } from "node:test";

const filename = fileURLToPath(new URL("../assets/branding/global-connect/journey-film/source/render.cjs", import.meta.url));
const source = await readFile(filename, "utf8");

async function runRenderer({ renderError, drainError, encoderError, prematureClose,
  ignoreTerminate, killError, destroyError } = {}) {
  const errors = [];
  const warnings = [];
  const deadlines = [];
  const calls = [];
  const child = new EventEmitter();
  child.stderr = new EventEmitter();
  child.stdin = new EventEmitter();
  child.alive = true;
  child.signals = [];
  child.stdin.write = () => {
    if (encoderError || prematureClose) {
      queueMicrotask(() => {
        child.alive = false;
        if (encoderError) child.emit("error", encoderError);
        child.emit("close", prematureClose ? 0 : null);
      });
      return false;
    }
    if (drainError) {
      queueMicrotask(() => child.stdin.emit("error", drainError));
      return false;
    }
    return true;
  };
  child.stdin.end = () => {
    child.alive = false;
    queueMicrotask(() => child.emit("close", 0));
  };
  child.stdin.destroy = () => { if (destroyError) throw destroyError; };
  child.kill = (signal) => {
    child.signals.push(signal);
    if (signal === "SIGTERM" && killError) throw killError;
    if (signal === "SIGTERM" && ignoreTerminate) return true;
    child.alive = false;
    queueMicrotask(() => child.emit("close", null, signal));
    return true;
  };
  let frame = 0;
  const process = { argv: ["node", filename, "--fps", "1"], env: {}, exitCode: 0 };
  const require = (name) => {
    if (name === "node:fs") return { writeFileSync() { throw new Error("Unexpected file write"); } };
    if (name === "node:path") return path;
    if (name === "node:events") return { once };
    if (name === "node:child_process") return { spawn: (...args) => { calls.push(args); return child; } };
    if (name === "@napi-rs/canvas") return { createCanvas() { throw new Error("No native canvas expected"); } };
    if (name === "./scene.cjs") return {
      DURATION: 2,
      render() {
        if (frame++ === 1 && renderError) throw renderError;
        return { data: () => Buffer.from([0, 1, 2, 255]) };
      },
    };
    throw new Error(`Unexpected module ${name}`);
  };
  const completion = vm.runInNewContext(source, {
    require, __dirname: path.dirname(filename), process,
    console: { log() {}, error: (error) => errors.push(error), warn: (message) => warnings.push(message) }, Date,
    setTimeout: ignoreTerminate || killError ? (callback, deadline) => {
      deadlines.push(deadline);
      queueMicrotask(callback);
      return 0;
    } : setTimeout,
    clearTimeout,
  }, { filename });
  await completion;
  return { child, errors, warnings, deadlines, calls, process };
}

test("encoder failure wakes a pending drain without an unhandled rejection or extra signal", async () => {
  const original = new Error("synthetic encoder acquisition failure");
  const result = await runRenderer({ encoderError: original });
  assert.equal(result.errors[0], original);
  assert.equal(result.child.alive, false);
  assert.equal(result.process.exitCode, 1);
  assert.deepEqual(result.child.signals, []);
});

test("premature successful encoder close cannot strand a drain or report a complete render", async () => {
  const result = await runRenderer({ prematureClose: true });
  assert.equal(result.errors[0].message, "Encoder closed before input completed");
  assert.equal(result.process.exitCode, 1);
  assert.equal(result.child.alive, false);
});

for (const mode of ["ignoreTerminate", "killError"]) {
  test(`${mode} uses bounded fallback and retains the original renderer failure`, async () => {
    const original = new Error("synthetic rendering failure");
    const result = await runRenderer({ renderError: original,
      [mode]: mode === "killError" ? new Error("synthetic signal error") : true });
    assert.equal(result.errors[0], original);
    assert.equal(result.process.exitCode, 1);
    assert.equal(result.child.alive, false);
    assert.deepEqual(result.child.signals, ["SIGTERM", "SIGKILL"]);
    assert.ok(result.deadlines.length > 0);
    assert.ok(result.deadlines.every((deadline) => deadline === 5000));
  });
}

test("secondary input cleanup failure does not mask the original renderer error", async () => {
  const original = new Error("synthetic rendering failure");
  const result = await runRenderer({ renderError: original, destroyError: new Error("synthetic destroy failure") });
  assert.equal(result.errors[0], original);
  assert.equal(result.child.alive, false);
  assert.deepEqual(result.warnings, ["Encoder input cleanup failed"]);
});

test("healthy ordinary renderer preserves encoding arguments and successful completion", async () => {
  const result = await runRenderer();
  assert.equal(result.process.exitCode, 0);
  assert.deepEqual(result.errors, []);
  assert.equal(result.child.alive, false);
  assert.deepEqual(result.child.signals, []);
  assert.equal(result.calls.length, 1);
  assert.equal(result.calls[0][0], "ffmpeg");
  assert.equal(result.calls[0][1].at(-1), path.resolve(path.dirname(filename), "../journey-film-web.mp4"));
  assert.equal(result.calls[0][2].windowsHide, true);
});

for (const failure of ["renderError", "drainError"]) {
  test(`${failure} preserves the triggering error and finishes its owned encoder`, async () => {
    const original = new Error(`synthetic ${failure}`);
    const result = await runRenderer({ [failure]: original });
    assert.equal(result.process.exitCode, 1);
    assert.equal(result.errors[0], original);
    assert.equal(result.child.alive, false);
    assert.deepEqual(result.child.signals, ["SIGTERM"]);
  });
}
