interface AuditVulnerability {
  readonly severity?: string;
  readonly via?: readonly (string | { readonly url?: string })[];
}

interface AuditReport {
  readonly vulnerabilities?: Readonly<Record<string, AuditVulnerability>>;
}

export function collectAdvisoryUrls(
  vulnerabilityName: string,
  vulnerabilities: Readonly<Record<string, AuditVulnerability>>,
): Set<string>;

export function findUnexpectedVulnerabilities(
  report: AuditReport,
): Array<{ readonly name: string; readonly advisoryUrls: readonly string[] }>;
