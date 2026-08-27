import { englishMessages } from '@/core/localization/messages';

import {
  LivenessCompletionSchema,
  MyPhotosExperienceStateSchema,
  MyPhotosSummarySchema,
  type MyPhotosSummary,
} from '../../api/contracts';
import { myPhotosStatePresentation } from '../summary-state';

const NOW = '2026-08-23T06:00:00.000Z';
const GROUP_ID = '11111111-1111-4111-8111-111111111111';

function summary(experienceState: MyPhotosSummary['experience_state']): MyPhotosSummary {
  return MyPhotosSummarySchema.parse({
    group_id: GROUP_ID,
    group_name: 'Synthetic MICE Trip',
    experience_state: experienceState,
    server_time: NOW,
    capability: {
      feature_enabled: experienceState !== 'feature_unavailable',
      provider_ready: !['provider_not_configured', 'provider_unavailable'].includes(experienceState),
      provider_state: experienceState === 'provider_not_configured'
        ? 'not_configured'
        : experienceState === 'provider_unavailable'
          ? 'temporarily_unavailable'
          : 'ready',
      client_flow: experienceState === 'provider_not_configured' ? 'unavailable' : 'development_simulator',
      supported_challenge_modes: ['movement_and_light', 'movement_only'],
      retryable: experienceState !== 'provider_not_configured',
    },
    gallery: {
      status: 'ready',
      published_revision: 3,
      media_version: 3,
      face_index_version: 2,
      total_asset_count: 5_000,
      indexed_asset_count: 5_000,
      failed_asset_count: 0,
      all_group_photos_enabled: true,
      published_at: NOW,
      updated_at: NOW,
    },
    consent: {
      required: experienceState === 'consent_required',
      required_version: 'consent-v1',
      accepted_version: experienceState === 'consent_required' ? null : 'consent-v1',
      accepted_at: experienceState === 'consent_required' ? null : NOW,
      purpose: 'Search only this selected trip.',
      biometric_data_used: 'A short-lived reference frame.',
      retention: 'Retained only under the reviewed policy.',
      provider_processing: 'Processed by the configured provider.',
      deletion: 'Can be revoked and deleted.',
    },
    enrollment: {
      status: experienceState === 'consent_required' ? 'consent_required' : 'enrolled',
      reference_version: 1,
      attempts_remaining: 3,
      cooldown_until: null,
      enrolled_at: NOW,
      updated_at: NOW,
    },
    search: {
      id: '22222222-2222-4222-8222-222222222222',
      status: experienceState === 'searching' ? 'searching' : 'complete',
      processed_face_count: 4_000,
      total_face_count: 5_000,
      progress_percent: 80,
      matched_photo_count: 57,
      best_match_count: 43,
      possible_match_count: 14,
      started_at: NOW,
      completed_at: experienceState === 'searching' ? null : NOW,
      error_code: null,
    },
    results: {
      snapshot_revision: 3,
      match_count: 57,
      new_photo_count: 4,
      downloadable_count: 56,
      preparing_count: 1,
      last_updated_at: NOW,
    },
  });
}

describe('My Photos explicit summary state copy', () => {
  it.each(MyPhotosExperienceStateSchema.options)('renders a distinct nonempty %s presentation', (state) => {
    const presentation = myPhotosStatePresentation(summary(state), englishMessages);
    expect(presentation.title.trim()).not.toBe('');
    expect(presentation.message.trim()).not.toBe('');
    expect(['none', 'refresh', 'open_face_scan']).toContain(presentation.action);
  });

  it('derives complete and partial offline states without mutating cached server state', () => {
    const cached = summary('matches_ready');
    const complete = myPhotosStatePresentation(cached, englishMessages, {
      source: 'offline', partial: false,
    });
    const partial = myPhotosStatePresentation(cached, englishMessages, {
      source: 'offline', partial: true,
    });
    expect(cached.experience_state).toBe('matches_ready');
    expect(complete.message).toBe(englishMessages.myPhotosOffline());
    expect(partial.message).toBe(englishMessages.myPhotosPartiallyOffline());
  });

  it('keeps access revocation authoritative even if older results are cached', () => {
    const presentation = myPhotosStatePresentation(summary('access_expired'), englishMessages, {
      source: 'offline', partial: true,
    });
    expect(presentation.title).toBe(englishMessages.myPhotosAccessRevoked());
    expect(presentation.tone).toBe('danger');
  });

  it('keeps a configured transient provider distinct from fail-closed not-configured state', () => {
    const transient = summary('provider_unavailable');
    expect(transient.capability).toMatchObject({
      provider_ready: false,
      provider_state: 'temporarily_unavailable',
      client_flow: 'development_simulator',
      retryable: true,
    });
    expect(() => MyPhotosSummarySchema.parse({
      ...transient,
      capability: { ...transient.capability, client_flow: 'unavailable' },
    })).toThrow();

    const notConfigured = summary('provider_not_configured');
    expect(notConfigured.capability).toMatchObject({
      provider_ready: false,
      provider_state: 'not_configured',
      client_flow: 'unavailable',
      retryable: false,
    });
  });

  it('rejects fractional backend search progress', () => {
    const value = summary('searching');
    expect(() => MyPhotosSummarySchema.parse({
      ...value,
      search: { ...value.search!, progress_percent: 80.5 },
    })).toThrow();
  });

  it('accepts an empty ready result set only at its positive completed snapshot', () => {
    const value = summary('no_matches');
    const empty = {
      ...value,
      search: {
        ...value.search!,
        matched_photo_count: 0,
        best_match_count: 0,
        possible_match_count: 0,
      },
      results: {
        ...value.results,
        snapshot_revision: 3,
        match_count: 0,
        new_photo_count: 0,
        downloadable_count: 0,
        preparing_count: 0,
      },
    };
    expect(() => MyPhotosSummarySchema.parse(empty)).not.toThrow();
    expect(() => MyPhotosSummarySchema.parse({
      ...empty,
      results: { ...empty.results, snapshot_revision: 0 },
    })).toThrow('Passenger result snapshot revision is inconsistent');
  });

  it('accepts an expired access summary when its ready gallery retains the published revision', () => {
    const value = summary('access_expired');
    const expiredReadyGallery = {
      ...value,
      search: null,
      results: {
        snapshot_revision: value.gallery.published_revision,
        match_count: 0,
        new_photo_count: 0,
        downloadable_count: 0,
        preparing_count: 0,
        last_updated_at: null,
      },
    };

    expect(MyPhotosSummarySchema.parse(expiredReadyGallery)).toMatchObject({
      experience_state: 'access_expired',
      gallery: { status: 'ready', published_revision: 3 },
      search: null,
      results: {
        snapshot_revision: 3,
        match_count: 0,
        last_updated_at: null,
      },
    });
  });

  it('accepts an expired Face Scan while enrollment remains ready for another attempt', () => {
    expect(LivenessCompletionSchema.parse({
      session_id: '33333333-3333-4333-8333-333333333333',
      session_status: 'expired',
      enrollment_status: 'ready',
      search_run_id: null,
      search_status: 'not_started',
      retryable: true,
      error_code: 'LIVENESS_SESSION_EXPIRED',
      cooldown_until: null,
    })).toMatchObject({
      session_status: 'expired',
      enrollment_status: 'ready',
    });
  });
});
