"use client";

import { useCallback, useReducer } from "react";
import { MAX_FAMILY_MEMBERS, MIN_FAMILY_MEMBERS } from "../components/upload-flow.constants";
import { familyUploadReducer, type FamilyMemberUpdate } from "../services/family-upload-state";
import { createFamilyMembers } from "../services/upload-flow-helpers";

export function useUploadFamily() {
  const [state, dispatch] = useReducer(familyUploadReducer, undefined, () => ({
    members: createFamilyMembers(MIN_FAMILY_MEMBERS), activeIndex: 0, countInput: String(MIN_FAMILY_MEMBERS),
  }));
  const setActiveFamilyIndex = useCallback((index: number) => dispatch({ type: "selected", index }), []);
  const updateFamilyMember = useCallback((index: number, update: FamilyMemberUpdate) => dispatch({ type: "member-updated", index, update }), []);
  const handleFamilyCountInput = (input: string) => dispatch({
    type: "count-edited", input,
    candidates: createFamilyMembers(Math.min(MAX_FAMILY_MEMBERS, Math.max(0, Number(input) || 0))),
  });
  const normalizeFamilyCountInput = () => dispatch({ type: "count-normalized", candidates: createFamilyMembers(MAX_FAMILY_MEMBERS) });
  return {
    familyMembers: state.members, activeFamilyIndex: state.activeIndex, familyCountInput: state.countInput,
    setActiveFamilyIndex, updateFamilyMember, handleFamilyCountInput, normalizeFamilyCountInput
  };
}
