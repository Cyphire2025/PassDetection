"use client";

import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { DraftQualifierInputs } from "../services/draft-input-contract";
import { FreshQualifierEditor } from "./fresh-qualifier-editor";

export function FreshQualifier(props: { state: DraftQualifierInputs; group: UploadLinkResponse }) {
  const proof = props.state.payload?.collection?.qualifier_selection_token ?? "";
  return <FreshQualifierEditor key={`${props.group.token}:${proof}`} {...props} />;
}
