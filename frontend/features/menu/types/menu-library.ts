export type DeleteTarget =
  | { kind: "category"; id: string; name: string; dishCount: number }
  | { kind: "dish"; id: string; name: string };

export type Feedback = { kind: "success" | "error"; message: string } | null;

export const CATEGORY_TONES = [
  "bg-orange-50 text-orange-700 ring-orange-100",
  "bg-emerald-50 text-emerald-700 ring-emerald-100",
  "bg-blue-50 text-blue-700 ring-blue-100",
  "bg-violet-50 text-violet-700 ring-violet-100",
  "bg-rose-50 text-rose-700 ring-rose-100",
  "bg-cyan-50 text-cyan-700 ring-cyan-100",
];
