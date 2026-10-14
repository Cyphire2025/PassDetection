export function draftUploadBody(file: File, revision: number, key: string, assetId: string | null) {
  const body = new FormData();
  body.set("file", file); body.set("expected_revision", String(revision));
  body.set("idempotency_key", key); body.set("expected_asset_id", assetId ?? "");
  return body;
}
