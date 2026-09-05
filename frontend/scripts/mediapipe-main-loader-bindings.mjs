// Hc starts graph, model, and JavaScript/WASM loading concurrently. A normal
// Promise.all rejects before siblings finish mutating the module globals.
// Drain every branch before propagating the first error so a retry can safely
// create a fresh instance; successful initialization still loads concurrently.
export function settleMediapipeInitialization(stages) {
  var failed = false;
  var firstFailure;
  return Promise.allSettled(stages.map(function(stage) {
    return Promise.resolve(stage).catch(function(error) {
      if (!failed) {
        failed = true;
        firstFailure = error;
      }
      throw error;
    });
  })).then(function(results) {
    if (failed) throw firstFailure;
    return results.map(function(result) { return result.value; });
  });
}

export function Ec(url) {
  var script = document.createElement("script");
  script.setAttribute("src", url);
  script.setAttribute("crossorigin", "anonymous");
  return new Promise(function(resolve, reject) {
    script.addEventListener("load", function() { resolve(); }, false);
    script.addEventListener("error", function() {
      reject(new Error("Unable to load face detection script: " + url));
    }, false);
    document.body.appendChild(script);
  });
}
