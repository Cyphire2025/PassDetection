export type PublicEnvironment = Readonly<Record<string, string | undefined>>;

export interface ProductionPublicEnvironment {
  readonly apiUrl: string;
  readonly appEnv: 'production';
  readonly demoMode: false;
  readonly easProjectId: string | undefined;
  readonly expoOwner: string | undefined;
  readonly updatesUrl: string | undefined;
  readonly updatesCodeSigningCertificate: string | undefined;
  readonly offlineLeaseIssuer: string;
  readonly offlineLeaseAudience: string;
  readonly offlineLeasePublicKeysJson: string;
  readonly sentryDsn: string;
}

export function validateProductionPublicEnvironment(
  source: PublicEnvironment,
): ProductionPublicEnvironment;

export function normalizeBuildFilePath(
  value: string | undefined,
): string | undefined;

export function validateOtaUpdateEnvironment(
  source: PublicEnvironment,
): void;

export function validateObservabilityBuildEnvironment(
  source: PublicEnvironment,
): Readonly<{ organization: string; project: string }>;

export function validateAppIntegrityBuildEnvironment(
  source: PublicEnvironment,
  production?: boolean,
): Readonly<{
  mode: 'disabled' | 'monitor' | 'enforce';
  cloudProjectNumber: string | undefined;
  appAttestEnvironment: 'development' | 'production' | undefined;
}>;
