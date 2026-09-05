// Serialized into the pinned Emscripten assets by patch-mediapipe-csp.mjs.
// These functions deliberately reference the existing Emscripten runtime helpers.
// Preserve conversion and destructor order; do not change the model or WASM.

export function createNamedFunction(name, body) {
  function namedFunction() {
    "use strict";
    return body.apply(this, arguments);
  }
  Object.defineProperty(namedFunction, "name", {
    value: makeLegalFunctionName(name),
    configurable: true,
  });
  return namedFunction;
}

export function craftInvokerFunction(humanName, argTypes, classType, cppInvokerFunc, cppTargetFunc) {
  var argCount = argTypes.length;
  if (argCount < 2) {
    throwBindingError("argTypes array size mismatch! Must at least get return value and 'this' types!");
  }
  var isClassMethodFunc = argTypes[1] !== null && classType !== null;
  var needsDestructorStack = false;
  for (var i = 1; i < argCount; ++i) {
    if (argTypes[i] !== null && argTypes[i].destructorFunction === undefined) {
      needsDestructorStack = true;
      break;
    }
  }
  var returnType = argTypes[0];
  var returns = returnType.name !== "void";
  var classParam = argTypes[1];
  var argumentTypes = argTypes.slice(2);
  var destructorFunctions = [];
  if (!needsDestructorStack) {
    for (var i = isClassMethodFunc ? 1 : 2; i < argCount; ++i) {
      destructorFunctions.push(argTypes[i].destructorFunction);
    }
  }
  function invokerFunction() {
    if (arguments.length !== argCount - 2) {
      throwBindingError("function " + humanName + " called with " + arguments.length + " arguments, expected " + (argCount - 2) + " args!");
    }
    var destructors = needsDestructorStack ? [] : null;
    var wired = [cppTargetFunc];
    if (isClassMethodFunc) wired.push(classParam.toWireType(destructors, this));
    for (var i = 0; i < argumentTypes.length; ++i) {
      wired.push(argumentTypes[i].toWireType(destructors, arguments[i]));
    }
    var rv = cppInvokerFunc.apply(undefined, wired);
    if (needsDestructorStack) {
      runDestructors(destructors);
    } else {
      for (var i = 0; i < destructorFunctions.length; ++i) {
        if (destructorFunctions[i] !== null) {
          destructorFunctions[i].call(undefined, wired[i + 1]);
        }
      }
    }
    if (returns) return returnType.fromWireType(rv);
  }
  Object.defineProperties(invokerFunction, {
    name: { value: makeLegalFunctionName(humanName), configurable: true },
    length: { value: argCount - 2, configurable: true },
  });
  return invokerFunction;
}

export function __emval_get_method_caller(argCount, argTypes) {
  var types = __emval_lookupTypes(argCount, argTypes);
  var retType = types[0];
  var signatureName = retType.name + "_$" + types.slice(1).map(function(t) { return t.name; }).join("_") + "$";
  var returnId = emval_registeredMethods[signatureName];
  if (returnId !== undefined) return returnId;
  var returns = !retType.isVoid;
  var parameters = [];
  var offset = 0;
  for (var i = 1; i < argCount; ++i) {
    parameters.push({ type: types[i], offset: offset, deleteObject: !!types[i].deleteObject });
    offset += types[i].argPackAdvance;
  }
  function methodCaller(handle, name, destructors, args) {
    var values = [];
    for (var i = 0; i < parameters.length; ++i) {
      values.push(parameters[i].type.readValueFromPointer(args + parameters[i].offset));
    }
    var rv = Reflect.apply(handle[name], handle, values);
    for (var i = 0; i < parameters.length; ++i) {
      if (parameters[i].deleteObject) parameters[i].type.deleteObject(values[i]);
    }
    if (returns) return retType.toWireType(destructors, rv);
  }
  Object.defineProperty(methodCaller, "name", {
    value: makeLegalFunctionName("methodCaller_" + signatureName),
    configurable: true,
  });
  returnId = __emval_addMethodCaller(methodCaller);
  emval_registeredMethods[signatureName] = returnId;
  return returnId;
}
