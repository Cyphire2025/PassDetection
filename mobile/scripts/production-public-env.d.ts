export type PublicEnvironment = Readonly<Record<string, string | undefined>>;

export interface ProductionPublicEnvironment {
  readonly apiUrl: string;
  readonly appEnv: 'production';
  readonly demoMode: false;
  readonly easProjectId: string;
  readonly expoOwner: string;
  readonly updatesUrl: string;
}

export function validateProductionPublicEnvironment(
  source: PublicEnvironment,
): ProductionPublicEnvironment;
