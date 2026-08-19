export function parseAndroidFingerprints(value: string | undefined): Set<string>;

export function validateAndroidAssetLinks(
  document: unknown,
  expectedFingerprints: ReadonlySet<string>,
): void;

export function validateAppleAppSiteAssociation(
  document: unknown,
  teamId: string,
): void;
