import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { assertNoStringCodeGeneration, findFunction, frontendRoot, mainSourceHashes, normalizeGeneratedAsset, patchAsset, patchMainAsset, sourceHashes, verifyOrWrite } from "./patch-mediapipe-csp.mjs";

const helperNames = ["makeLegalFunctionName", "createNamedFunction", "new_", "craftInvokerFunction", "__emval_get_method_caller"];
const runtime = `
var char_0 = 48, char_9 = 57;
var events = [];
function throwBindingError(message) { throw new Error(message); }
function runDestructors(stack) { while (stack.length) { var value = stack.pop(); stack.pop()(value); } }
var emval_registeredMethods = {};
var callers = [];
var lookupTypes;
function __emval_lookupTypes() { return lookupTypes; }
function __emval_addMethodCaller(caller) { callers.push(caller); return callers.length - 1; }
function converter(name, mode) {
  var type = {
    name: name,
    toWireType: function(stack, value) {
      events.push(["wire", this.name, value && value.tag ? value.tag : value, stack === null]);
      var wired = value && value.tag ? 21 : value * 10;
      if (mode === "stack") stack.push(function(v) { events.push(["stack-delete", name, v]); }, wired);
      return wired;
    },
    fromWireType: function(value) { events.push(["return", this.name, value]); return value + 1; }
  };
  if (mode !== "stack") type.destructorFunction = mode === "direct" ? function(value) { events.push(["delete", name, value]); } : null;
  return type;
}
function report(value) { return JSON.stringify({ value: value, events: events }); }
`;

function run(source, scenario, strings) {
  const helpers = helperNames.map((name) => findFunction(source, name).source).join("\n");
  const context = vm.createContext({}, { codeGeneration: { strings, wasm: true } });
  return new vm.Script(`${runtime}\n${helpers}\n${scenario}`).runInContext(context);
}

const scenarios = {
  "named functions preserve constructors, strict this, arguments, names and arity": `
    var f = createNamedFunction("Photo detector", function(a, b) { "use strict"; return [this === undefined, a + b]; });
    var ctor = createNamedFunction("9Photo", function(value) { this.value = value; });
    var value = new ctor(7);
    report([f(2, 3), f.name, f.length, ctor.name, value.value, value instanceof ctor]);
  `,
  "free invokers convert arguments and return values with direct destructors": `
    var f = craftInvokerFunction("check.photo", [converter("result"), null, converter("a", "direct"), converter("b")], null,
      function(target, a, b) { "use strict"; events.push(["invoke", this === undefined, target, a, b]); return a + b; }, 81);
    report([f(2, 3), f.name, f.length]);
  `,
  "class invokers convert and destroy receiver before parameters": `
    var f = craftInvokerFunction("Photo.check", [converter("result"), converter("receiver", "direct"), converter("a", "direct")], {},
      function(target, self, a) { events.push(["invoke", target, self, a]); return a; }, 9);
    report([f.call({tag: "photo"}, 4), f.name, f.length]);
  `,
  "destructor stacks retain LIFO cleanup and void return": `
    var f = craftInvokerFunction("Photo.check", [converter("void"), converter("receiver", "stack"), converter("a", "stack")], {},
      function(target, self, a) { events.push(["invoke", target, self, a]); return 999; }, 9);
    report([f.call({tag: "photo"}, 4), f.name, f.length]);
  `,
  "zero argument void invokers preserve arity": `
    var f = craftInvokerFunction("reset", [converter("void"), null], null,
      function(target) { events.push(["invoke", target]); return 999; }, 8);
    report([f(), f.name, f.length]);
  `,
  "arity and invalid type failures occur before invocation": `
    var f = craftInvokerFunction("check", [converter("void"), null, converter("a")], null, function() { events.push("unexpected"); }, 9);
    var errors = [];
    try { f(); } catch (e) { errors.push(e.message); }
    try { f(1, 2); } catch (e) { errors.push(e.message); }
    try { craftInvokerFunction("bad", [], null); } catch (e) { errors.push(e.message); }
    report(errors);
  `,
  "conversion and invocation errors preserve existing propagation": `
    var bad = converter("a", "stack");
    bad.toWireType = function() { events.push("convert-failure"); throw new Error("bad conversion"); };
    var f = craftInvokerFunction("check", [converter("result"), null, bad], null, function() { events.push("unexpected"); }, 9);
    var messages = [];
    try { f(1); } catch(e) { messages.push(e.message); }
    f = craftInvokerFunction("check", [converter("result"), null, converter("a", "stack")], null,
      function() { events.push("invoke-failure"); throw new Error("bad invocation"); }, 9);
    try { f(1); } catch(e) { messages.push(e.message); }
    report(messages);
  `,
  "emval calls read packed offsets, preserve receiver, clean objects and cache signatures": `
    lookupTypes = [
      {name: "result", toWireType: function(destructors, value) { events.push(["return", destructors.marker, value]); return value * 2; }},
      {name: "first", argPackAdvance: 8, readValueFromPointer: function(pointer) { events.push(["read", this.name, pointer]); return pointer; },
       deleteObject: function(value) { events.push(["delete", this.name, value]); }},
      {name: "second", argPackAdvance: 4, readValueFromPointer: function(pointer) { events.push(["read", this.name, pointer]); return pointer; }}
    ];
    var id = __emval_get_method_caller(3, 0);
    var secondId = __emval_get_method_caller(3, 0);
    var handle = {value: 5, sum: function(a, b) { events.push(["method", this.value, a, b]); return this.value + a + b; }};
    var result = callers[id](handle, "sum", {marker: "destructors"}, 100);
    report([result, id, secondId, callers.length, callers[id].name, callers[id].length]);
  `,
  "emval void methods have no return conversion": `
    lookupTypes = [{name: "void", isVoid: true, toWireType: function() { events.push("unexpected"); }}];
    var id = __emval_get_method_caller(1, 0);
    var result = callers[id]({ping: function() { events.push("ping"); return 2; }}, "ping", null, 0);
    report([result, callers[id].name, callers[id].length]);
  `,
  "emval captures return mode at registration and propagates method exceptions": `
    lookupTypes = [{name: "void", isVoid: true, toWireType: function() { events.push("unexpected"); }}];
    var id = __emval_get_method_caller(1, 0);
    lookupTypes[0].isVoid = false;
    callers[id]({ping: function() { events.push("ping"); return 2; }}, "ping", null, 0);
    try {
      callers[id]({ping: function() { events.push("failure"); throw new Error("method failed"); }}, "ping", null, 0);
    } catch (e) { events.push(e.message); }
    report(callers[id].length);
  `,
};

test("vendored assets are reproducibly patched and model/WASM hashes remain unchanged", async () => {
  await verifyOrWrite();
});

for (const filename of Object.keys(sourceHashes)) {
  const original = await readFile(path.join(frontendRoot, "node_modules/@mediapipe/face_detection", filename), "utf8");
  const patched = patchAsset(original, filename);
  test(`${filename}: upstream reproduces the strict CSP failure`, () => {
    assert.throws(() => run(original, 'createNamedFunction("test", function() {});', false), /Code generation from strings disallowed/);
  });
  test(`${filename}: rejects unreviewed source and removes all codegen sites`, () => {
    assert.throws(() => patchAsset(original + " ", filename), /Unrecognized upstream asset/);
    assert.throws(() => assertNoStringCodeGeneration(original), /String code generation remains/);
    assertNoStringCodeGeneration(patched);
  });
  test(`${filename}: CRLF generated checkout is equivalent but upstream hashes remain exact`, () => {
    assert.equal(normalizeGeneratedAsset(patched.replace(/\n/g, "\r\n")), patched);
    assert.throws(() => patchAsset(original.replace(/\n/g, "\r\n"), filename), /Unrecognized upstream asset/);
  });
  for (const [name, scenario] of Object.entries(scenarios)) {
    test(`${filename}: ${name}`, () => {
      assert.equal(run(patched, scenario, false), run(original, scenario, true));
    });
  }
}

const mainSource = await readFile(path.join(frontendRoot, "node_modules/@mediapipe/face_detection/face_detection.js"), "utf8");
const patchedMain = patchMainAsset(mainSource, "face_detection.js");

function mainRuntime(globals = {}) {
  const helpers = ["Ec", "Ic", "settleMediapipeInitialization"].map((name) => findFunction(patchedMain, name).source).join("\n");
  const context = vm.createContext(globals, { codeGeneration: { strings: false, wasm: true } });
  return new vm.Script(`
    function J(callback) { return Promise.resolve().then(function() {
      return callback({return: function(value) { return value; }});
    }); }
    ${helpers}
    ({ Ec: Ec, Ic: Ic, settle: settleMediapipeInitialization });
  `).runInContext(context);
}

test("main API patch is source-pinned, CSP compatible, CRLF tolerant and drains every concurrent group", () => {
  assert.equal(Object.keys(mainSourceHashes).length, 1);
  assert.throws(() => patchMainAsset(mainSource + " ", "face_detection.js"), /Unrecognized upstream asset/);
  assert.throws(() => patchMainAsset(mainSource.replace(/\n/g, "\r\n"), "face_detection.js"), /Unrecognized upstream asset/);
  assert.equal(normalizeGeneratedAsset(patchedMain.replace(/\n/g, "\r\n")), patchedMain);
  const initializer = findFunction(patchedMain, "Hc").source;
  assert.equal(initializer.includes("Promise.all("), false);
  assert.equal(initializer.split("settleMediapipeInitialization(").length - 1, 3);
  assertNoStringCodeGeneration(patchedMain);
});

test("initialization still runs concurrently and returns the original ordered successful results", async () => {
  const { settle } = mainRuntime();
  const stages = [Promise.resolve(3), 4, Promise.resolve(5)];
  assert.equal(JSON.stringify(await settle(stages)), JSON.stringify(await Promise.all(stages)));
});

test("graph failure waits for delayed loader and nested data work before a retry can start", async () => {
  const { settle } = mainRuntime();
  const originalFailure = new Error("graph fetch failed");
  let finishLoader;
  let finishModel;
  const loader = new Promise((resolve) => { finishLoader = resolve; });
  const model = new Promise((resolve) => { finishModel = resolve; });
  const data = settle([Promise.resolve("data"), model]);
  const initialization = settle([loader, data, Promise.reject(originalFailure)]);
  let completed = false;
  const rejection = initialization.catch((error) => { completed = true; return error; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(completed, false);
  finishLoader("wasm ready");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(completed, false);
  finishModel("model ready");
  assert.equal(await rejection, originalFailure);
  assert.equal(completed, true);
});

test("draining preserves the first chronological rejection instead of input-array order", async () => {
  const { settle } = mainRuntime();
  let rejectLater;
  const later = new Promise((resolve, reject) => { rejectLater = reject; });
  const firstFailure = new Error("first failure");
  const initialization = settle([later, Promise.reject(firstFailure)]);
  const rejection = initialization.catch((error) => error);
  await new Promise((resolve) => setImmediate(resolve));
  rejectLater(new Error("later failure"));
  assert.equal(await rejection, firstFailure);
});

test("script success resolves and script network/HTTP failure rejects explicitly", async () => {
  const scripts = [];
  const { Ec } = mainRuntime({ document: {
    createElement(tag) {
      assert.equal(tag, "script");
      return { attributes: {}, handlers: {},
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(name, handler) { this.handlers[name] = handler; },
      };
    },
    body: { appendChild(script) { scripts.push(script); } },
  } });
  const success = Ec("/face_detection_solution_wasm_bin.js");
  assert.deepEqual(scripts[0].attributes, { src: "/face_detection_solution_wasm_bin.js", crossorigin: "anonymous" });
  scripts[0].handlers.load();
  assert.equal(await success, undefined);
  const failure = Ec("/missing-loader.js");
  scripts[1].handlers.error();
  await assert.rejects(failure, /Unable to load face detection script: \/missing-loader.js/);
});

test("asset HTTP errors reject before consuming bodies; a fresh detector retries and caches successful bytes", async () => {
  let status = 522;
  let fetched = 0;
  let bodiesRead = 0;
  const bytes = new Uint8Array([1, 2, 3]).buffer;
  const { Ic } = mainRuntime({ fetch: async (url) => {
    fetched += 1;
    assert.equal(url, "/mediapipe/graph.binarypb");
    return { ok: status === 200, status, arrayBuffer: async () => { bodiesRead += 1; return bytes; } };
  } });
  const detector = () => ({ H: {}, locateFile: (name) => "/mediapipe/" + name });
  await assert.rejects(Ic(detector(), "graph.binarypb"), /HTTP 522/);
  assert.equal(bodiesRead, 0);
  status = 200;
  const fresh = detector();
  assert.equal(await Ic(fresh, "graph.binarypb"), bytes);
  assert.equal(await Ic(fresh, "graph.binarypb"), bytes);
  assert.equal(fetched, 2);
  assert.equal(bodiesRead, 1);
});
