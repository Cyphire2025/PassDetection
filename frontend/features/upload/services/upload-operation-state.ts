/** One active document operation; generation checks reject late async results. */
export type UploadOperationKind = "upload" | "resume" | "retry" | "replace" | "submit";
export type UploadOperationState =
  | { status: "idle"; generation: number }
  | { status: "active"; generation: number; kind: UploadOperationKind };
export type UploadOperationEvent =
  | { type: "started"; generation: number; kind: UploadOperationKind }
  | { type: "finished"; generation: number };

export function uploadOperationReducer(state: UploadOperationState, event: UploadOperationEvent): UploadOperationState {
  if (event.type === "started") {
    return event.generation > state.generation
      ? { status: "active", generation: event.generation, kind: event.kind }
      : state;
  }
  return event.generation === state.generation
    ? { status: "idle", generation: state.generation }
    : state;
}
