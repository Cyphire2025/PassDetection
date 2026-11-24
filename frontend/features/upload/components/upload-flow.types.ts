export type AgentEmployeeType = "" | "agent" | "employee";

export interface PassportDocumentBundle {
  front: File | null;
  back: File | null;
  cover: File | null;
  back_cover: File | null;
  frontSource: "camera" | "file" | null;
  backSource: "camera" | "file" | null;
  frontManuallyCropped: boolean;
  backManuallyCropped: boolean;
}
