export const STEP_UP_REQUIRED_EVENT = "passdetection:step-up-required";

let pendingStepUp: {
  promise: Promise<void>;
  resolve: () => void;
  reject: (reason: unknown) => void;
} | null = null;

export function requestAuthenticationStepUp(): Promise<void> {
  if (pendingStepUp) return pendingStepUp.promise;
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Authentication step-up requires an interactive browser"));
  }
  let resolvePromise!: () => void;
  let rejectPromise!: (reason: unknown) => void;
  const promise = new Promise<void>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  pendingStepUp = {
    promise,
    resolve: () => {
      pendingStepUp = null;
      resolvePromise();
    },
    reject: (reason) => {
      pendingStepUp = null;
      rejectPromise(reason);
    },
  };
  window.dispatchEvent(new CustomEvent(STEP_UP_REQUIRED_EVENT));
  return promise;
}

export function completeAuthenticationStepUp(): void {
  pendingStepUp?.resolve();
}

export function cancelAuthenticationStepUp(): void {
  pendingStepUp?.reject({
    code: "STEP_UP_CANCELLED",
    message: "Identity confirmation was cancelled.",
  });
}
