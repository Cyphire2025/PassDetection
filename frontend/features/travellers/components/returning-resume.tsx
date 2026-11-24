"use client";
import { useReturningResume } from "../hooks/use-returning-resume";
import { ReturningResumeContent, type ReturningResumeProps } from "./returning-resume-content";

export function ReturningResume(props: ReturningResumeProps) {
  const state = useReturningResume(props.token);
  return <ReturningResumeContent {...props} {...state} />;
}
