"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
  passportsApi,
  type PassportImageLibraryItem,
  type VisaAiGenerationJob,
  type VisaAiLibraryImage,
} from "../api/passports.api";
import { waitForVisaAiGenerationJob } from "../services/visa-ai-generation-polling";
import { readEditError } from "../utils/passport-image-editor-state";

const DEFAULT_VISA_AI_PROMPT =
  "Regenerate the image of the person in this image to a studio clicked photo for visa application , it should have a plain white background , keep the current details preserved";

interface VisaAiGenerationOptions {
  submissionId: string;
  isVisaPhoto: boolean;
  canGenerate: boolean;
  imageLibrary: PassportImageLibraryItem[];
  setImageLibrary: Dispatch<SetStateAction<PassportImageLibraryItem[]>>;
  setError: Dispatch<SetStateAction<string | null>>;
}

export function useVisaAiImageGeneration({
  submissionId,
  isVisaPhoto,
  canGenerate,
  imageLibrary,
  setImageLibrary,
  setError,
}: VisaAiGenerationOptions) {
  const [aiPrompt, setAiPrompt] = useState(isVisaPhoto ? DEFAULT_VISA_AI_PROMPT : "");
  const [isGenerating, setIsGenerating] = useState(false);
  const [featuredGenerationId, setFeaturedGenerationId] = useState<string | null>(null);
  const aiRequestRef = useRef<AbortController | null>(null);
  const generatingRef = useRef(false);
  useEffect(() => () => aiRequestRef.current?.abort(), []);

  useEffect(() => {
    if (!isVisaPhoto) return;
    const controller = new AbortController();
    aiRequestRef.current?.abort();
    aiRequestRef.current = controller;
    void (async () => {
      try {
        const activeJob = await passportsApi.getActiveVisaAiGenerationJob(
          submissionId,
          controller.signal,
        );
        if (!activeJob || controller.signal.aborted) return;
        setAiPrompt(activeJob.prompt);
        generatingRef.current = true;
        setIsGenerating(true);
        const terminalJob = await waitForVisaAiGenerationJob(
          submissionId,
          activeJob,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          applyTerminalVisaAiJob(
            terminalJob,
            setImageLibrary,
            setFeaturedGenerationId,
            setError,
          );
        }
      } catch (resumeError) {
        if (!controller.signal.aborted) {
          setError(readEditError(
            resumeError,
            "Could not resume the saved Visa photo generation.",
          ));
        }
      } finally {
        if (aiRequestRef.current === controller) {
          aiRequestRef.current = null;
          generatingRef.current = false;
          setIsGenerating(false);
        }
      }
    })();
    return () => controller.abort();
  }, [isVisaPhoto, submissionId, setError, setImageLibrary]);

  const generateAiPreview = async () => {
    const prompt = aiPrompt.trim().split(/\s+/).join(" ");
    if (!canGenerate || prompt.length < 3 || generatingRef.current) return;
    generatingRef.current = true;
    setError(null);
    setIsGenerating(true);
    aiRequestRef.current?.abort();
    const controller = new AbortController();
    aiRequestRef.current = controller;
    try {
      const job = await passportsApi.createVisaAiGenerationJob(
        submissionId,
        prompt,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setAiPrompt(job.prompt);
      const terminalJob = await waitForVisaAiGenerationJob(
        submissionId,
        job,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        applyTerminalVisaAiJob(
          terminalJob,
          setImageLibrary,
          setFeaturedGenerationId,
          setError,
        );
      }
    } catch (generationError) {
      if (!controller.signal.aborted) {
        setError(readEditError(
          generationError,
          "Could not generate the Visa photo.",
        ));
      }
    } finally {
      if (aiRequestRef.current === controller) {
        aiRequestRef.current = null;
        generatingRef.current = false;
        setIsGenerating(false);
      }
    }
  };

  return {
    aiPrompt,
    setAiPrompt,
    isGenerating,
    featuredGenerationId: featuredGenerationId ?? imageLibrary.find((item) => item.source === "ai_generated")?.id ?? null,
    generateAiPreview,
  };
}

function applyTerminalVisaAiJob(
  job: VisaAiGenerationJob,
  setLibrary: Dispatch<SetStateAction<PassportImageLibraryItem[]>>,
  setFeaturedGenerationId: Dispatch<SetStateAction<string | null>>,
  setError: Dispatch<SetStateAction<string | null>>,
) {
  if (job.status === "succeeded" && job.result) {
    const result = job.result;
    const commonLibraryItem = toCommonAiLibraryItem(result);
    setLibrary((current) => [
      commonLibraryItem,
      ...current.filter((item) => item.id !== result.id),
    ]);
    setFeaturedGenerationId(result.id);
    setError(null);
    return;
  }
  if (job.status === "failed") {
    setError(
      job.error_message?.trim()
      || "Could not generate the Visa photo. Please try again.",
    );
    return;
  }
  setError("The Visa photo was generated, but its saved result is unavailable.");
}

function toCommonAiLibraryItem(
  item: VisaAiLibraryImage,
): PassportImageLibraryItem {
  return {
    ...item,
    image_type: "visa_photo",
    source: "ai_generated",
  };
}

