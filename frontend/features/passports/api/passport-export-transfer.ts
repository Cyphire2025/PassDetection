import { downloadStreamedResponse, type StreamedDownloadRequest } from "@/lib/api/streamed-download";
import { capturePassportOperationOwner, type PassportRequestConfig } from "./passport-request-config";

/** One owner spans the Save As picker, private response body and finished export. */
export async function downloadPassportExport(
  request: StreamedDownloadRequest,
  requestConfig?: PassportRequestConfig,
) {
  const owner = capturePassportOperationOwner(requestConfig);
  const result = await downloadStreamedResponse({
    ...request,
    expectedOwnerUserId: owner.requestConfig.expectedOwnerUserId,
  });
  owner.assertCurrent();
  return result;
}
