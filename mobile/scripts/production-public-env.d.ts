export type PublicEnvironment = Readonly<Record<string, string | undefined>>;

export interface ProductionPublicEnvironment {
  readonly apiUrl: string;
  readonly appEnv: 'production';
  readonly demoMode: false;
  readonly easProjectId: string | undefined;
  readonly expoOwner: string | undefined;
  readonly updatesUrl: string | undefined;
}

export function validateProductionPublicEnvironment(
  source: PublicEnvironment,
): ProductionPublicEnvironment;
