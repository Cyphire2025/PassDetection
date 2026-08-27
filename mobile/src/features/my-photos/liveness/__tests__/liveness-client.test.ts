import { LivenessSessionSchema } from '../../api/contracts';
import {
  createAndroidFaceLivenessBridge,
  developmentLivenessSimulatorPolicy,
} from '../liveness-client';

const session = {
  session_id: '11111111-1111-4111-8111-111111111111',
  status: 'created',
  challenge_mode: 'movement_and_light',
  client_flow: 'development_simulator',
  native_launch_handle: null,
  expires_at: '2026-08-23T10:05:00.000Z',
  attempts_remaining: 3,
  photosensitivity_warning: 'Changing light may affect photosensitive passengers.',
} as const;

describe('development Face Scan safety boundary', () => {
  it('requires explicit development flow, development build, and loopback backend', () => {
    expect(developmentLivenessSimulatorPolicy({
      appEnv: 'development', apiHostname: '10.0.2.2', clientFlow: 'development_simulator',
    })).toBe(true);
    expect(developmentLivenessSimulatorPolicy({
      appEnv: 'production', apiHostname: '127.0.0.1', clientFlow: 'development_simulator',
    })).toBe(false);
    expect(developmentLivenessSimulatorPolicy({
      appEnv: 'development', apiHostname: 'api.example.com', clientFlow: 'development_simulator',
    })).toBe(false);
    expect(developmentLivenessSimulatorPolicy({
      appEnv: 'development', apiHostname: '127.0.0.1', clientFlow: 'native',
    })).toBe(false);
  });

  it('keeps native launch material strict, opaque, and absent from the simulator', () => {
    expect(LivenessSessionSchema.safeParse(session).success).toBe(true);
    expect(LivenessSessionSchema.safeParse({
      ...session,
      native_launch_handle: 'must-not-enter-js-simulator',
    }).success).toBe(false);
    expect(LivenessSessionSchema.safeParse({
      ...session,
      client_flow: 'native',
      native_launch_handle: null,
    }).success).toBe(false);
    expect(LivenessSessionSchema.safeParse({
      ...session,
      client_flow: 'native',
      native_launch_handle: 'opaque-provider-launch-handle',
    }).success).toBe(true);
    expect(LivenessSessionSchema.safeParse({
      ...session,
      unexpected_provider_payload: true,
    }).success).toBe(false);
  });
});

describe('Android native Face Liveness bridge', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date('2026-08-27T08:00:00.000Z'));
  });

  afterEach(() => jest.useRealTimers());

  it('fails closed when the native module or complete native configuration is absent', async () => {
    expect(createAndroidFaceLivenessBridge({ platform: 'android', module: undefined }).available)
      .toBe(false);
    expect(createAndroidFaceLivenessBridge({
      platform: 'android',
      module: {
        available: true,
        provider: 'cognito_identity_pool',
        present: jest.fn(),
        cancel: jest.fn(),
      },
    }).available).toBe(false);
    await expect(createAndroidFaceLivenessBridge({
      platform: 'ios',
      module: {
        available: true,
        provider: 'cognito_identity_pool',
        region: 'ap-south-1',
        present: jest.fn(),
        cancel: jest.fn(),
      },
    }).present({
      providerSessionId: 'provider-session',
      expiresAt: '2026-08-27T08:02:00.000Z',
    })).resolves.toBe('unavailable');
  });

  it('passes only a bounded provider session and expiry to native code', async () => {
    const present = jest.fn(async () => 'completed');
    const cancel = jest.fn(async () => undefined);
    const bridge = createAndroidFaceLivenessBridge({
      platform: 'android',
      module: {
        available: true,
        provider: 'cognito_identity_pool',
        region: 'ap-south-1',
        present,
        cancel,
      },
    });

    expect(bridge.available).toBe(true);
    expect(bridge.region).toBe('ap-south-1');
    await expect(bridge.present({
      providerSessionId: 'provider-session-123',
      expiresAt: '2026-08-27T08:02:00.000Z',
    })).resolves.toBe('completed');
    expect(present).toHaveBeenCalledWith(
      'provider-session-123',
      '2026-08-27T08:02:00.000Z',
    );
    expect(cancel).not.toHaveBeenCalled();
  });

  it('bounds native input/output and cancels the native dialog on abort', async () => {
    let resolveNative!: (value: string) => void;
    const present = jest.fn(() => new Promise<string>((resolve) => {
      resolveNative = resolve;
    }));
    const cancel = jest.fn(async () => undefined);
    const bridge = createAndroidFaceLivenessBridge({
      platform: 'android',
      module: {
        available: true,
        provider: 'cognito_identity_pool',
        region: 'ap-south-1',
        present,
        cancel,
      },
    });
    await expect(bridge.present({
      providerSessionId: 'contains whitespace',
      expiresAt: '2026-08-27T08:02:00.000Z',
    })).resolves.toBe('failed');
    await expect(bridge.present({
      providerSessionId: 'provider-session',
      expiresAt: '2026-08-27T08:04:00.000Z',
    })).resolves.toBe('expired');

    const abort = new AbortController();
    const outcome = bridge.present({
      providerSessionId: 'provider-session',
      expiresAt: '2026-08-27T08:02:00.000Z',
    }, abort.signal);
    abort.abort();
    await expect(outcome).resolves.toBe('cancelled');
    expect(cancel).toHaveBeenCalledTimes(1);
    resolveNative('completed');
  });
});
